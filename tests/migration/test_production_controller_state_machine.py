from datetime import UTC,datetime,timedelta
import json
import pytest
from core.migration.production_controller import *
def ident(run="T03FINAL-20260829T120000Z-test",**kw):
 d=dict(run_id=run,started_at=datetime.now(UTC).isoformat(),administrator=True,formal_python="x",branch="dev/v5.3.2",head="h",canonical_path="c",initial_runtime_classification="LEGACY_V3",production_cutover=True);d.update(kw);return ControllerIdentity(**d)
def ev(i):
 t=datetime.now(UTC).isoformat();return {n:GateEvidence(n,True,i.run_id,t,"test","evidence.json") for n in PRE_SWAP_GATES}
def make(tmp_path,results=None,**kw):
 calls=[];roll=[];restore=[]; results=results or {};ops=ProductionOperations(lambda n:calls.append(n) or results.get(n,{"passed":True,"disposition":"MUTATED"}),lambda:roll.append(1) or {"passed":True,"verified":True},lambda:restore.append(1) or {"passed":True});return T03ProductionController(ident(**kw),tmp_path/"run",ops),calls,roll,restore
def ready(c):
 for s in [ControllerState.ENV_VERIFIED,ControllerState.PREFLIGHT_PASS,ControllerState.LEGACY_VERIFIED,ControllerState.MAINTENANCE_ENTERED,ControllerState.LEGACY_STABILIZED,ControllerState.SOURCE_FROZEN,ControllerState.ARCHIVE_INITIALIZED,ControllerState.CANDIDATE_A_BUILT,ControllerState.CANDIDATE_A_FIRST_PASS,ControllerState.CANDIDATE_A_RESTART_PASS,ControllerState.CANDIDATE_A_STABILIZED,ControllerState.CANDIDATE_A_VERIFIED,ControllerState.CANDIDATE_B_EVIDENCE_COMPLETE,ControllerState.CANDIDATE_B_STABILIZED,ControllerState.CANDIDATE_B_SEALED,ControllerState.A0_B0_PASS,ControllerState.ARCHIVE_FINALIZED,ControllerState.RUNTIME_CONFIG_BOUND,ControllerState.MAINTENANCE_FRESH]:c.transition(s)
def test_graph_terminal_and_identity(tmp_path):
 c,*_=make(tmp_path)
 with pytest.raises(ControllerError):c.transition(ControllerState.ATOMIC_REPLACED)
 c.transition(ControllerState.PRE_SWAP_ABORT)
 with pytest.raises(ControllerError):c.transition(ControllerState.ENV_VERIFIED)
 for field,value in [("administrator",False),("production_cutover",False),("initial_runtime_classification","V5")]:
  c,*_=make(tmp_path/field,**{field:value});ready(c)
  with pytest.raises(ControllerError):c.require_pre_swap(ev(c.identity))
def test_evidence_rejections_no_swap(tmp_path):
 c,calls,*_=make(tmp_path);ready(c);g=ev(c.identity);g.pop("tests")
 with pytest.raises(ControllerError):c.require_pre_swap(g)
 for evidence in [GateEvidence("tests",True,"old",datetime.now(UTC).isoformat(),"x","x"),GateEvidence("tests",True,c.identity.run_id,(datetime.now(UTC)-timedelta(hours=1)).isoformat(),"x","x"),GateEvidence("tests",True,c.identity.run_id,"bad","x","x"),GateEvidence("tests",True,c.identity.run_id,(datetime.now(UTC)+timedelta(hours=1)).isoformat(),"x","x")]:
  c,*_=make(tmp_path/str(hash(str(evidence))));ready(c);g=ev(c.identity);g["tests"]=evidence
  with pytest.raises(ControllerError):c.require_pre_swap(g)
 assert calls==[]
@pytest.mark.parametrize("result,terminal,rolls",[( {"passed":False,"disposition":"NOT_ATTEMPTED"},ControllerState.PRE_SWAP_ABORT,0),({"passed":False,"disposition":"ATTEMPTED_NO_MUTATION_PROVEN"},ControllerState.PRE_SWAP_ABORT,0),({"passed":False,"disposition":"INDETERMINATE"},ControllerState.ROLLED_BACK,1)])
def test_atomic_dispositions(tmp_path,result,terminal,rolls):
 c,calls,roll,_=make(tmp_path,{"ATOMIC_REPLACEMENT":result});ready(c);c.require_pre_swap(ev(c.identity))
 with pytest.raises(ControllerError):c.atomic_replace()
 assert c.state is terminal and roll==[1]*rolls
def test_atomic_intent_precedes_callback_and_rollback_failure(tmp_path):
 observed=[]
 c,calls,roll,_=make(tmp_path);c.operations.call=lambda n:observed.append(json.loads((c.run_root/"CONTROLLER_STATE.json").read_text())["mutation_intent"]) or {"passed":True,"disposition":"MUTATED"};ready(c);c.require_pre_swap(ev(c.identity));c.atomic_replace();assert observed[0]["status"]=="INTENT_PERSISTED"
 c,calls,roll,_=make(tmp_path/"x",{"P4":{"passed":False}});c.operations.rollback=lambda:{"passed":False};ready(c);c.require_pre_swap(ev(c.identity));c.atomic_replace()
 # post-swap wiring is separately tested after the adapter exists; direct rollback still must fail terminally
 with pytest.raises(ControllerError):c._rollback("inject")
 assert c.state is ControllerState.ROLLBACK_FAILED and c.rollback_attempt_count==1
def test_post_swap_failure_rolls_back_once_and_locks(tmp_path):
 c,calls,roll,_=make(tmp_path,{"P4":{"passed":False}});ready(c);c.require_pre_swap(ev(c.identity));c.atomic_replace()
 with pytest.raises(ControllerError):c.post_swap_gate("P4",ControllerState.P4_PASS)
 assert c.state is ControllerState.ROLLED_BACK and roll==[1] and c.production_v5_atomic_replacement_count==1
 with pytest.raises(ControllerError):c.post_swap_gate("V5_STARTED",ControllerState.V5_STARTED)
 assert roll==[1]
