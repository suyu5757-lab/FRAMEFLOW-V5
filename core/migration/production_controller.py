"""Durable, fail-closed state machine for the formal live T03 controller.

It deliberately contains no migration, SQLite, task, port, or runtime logic.
Those behaviours are injected from their existing authoritative primitives.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Mapping

CONTROLLER_VERSION = "2"


class ControllerError(RuntimeError): pass
class ControllerState(StrEnum):
    INIT="INIT"; ENV_VERIFIED="ENV_VERIFIED"; PREFLIGHT_PASS="PREFLIGHT_PASS"; LEGACY_VERIFIED="LEGACY_VERIFIED"; MAINTENANCE_ENTERED="MAINTENANCE_ENTERED"; LEGACY_STABILIZED="LEGACY_STABILIZED"; SOURCE_FROZEN="SOURCE_FROZEN"; ARCHIVE_INITIALIZED="ARCHIVE_INITIALIZED"; CANDIDATE_A_BUILT="CANDIDATE_A_BUILT"; CANDIDATE_A_FIRST_PASS="CANDIDATE_A_FIRST_PASS"; CANDIDATE_A_RESTART_PASS="CANDIDATE_A_RESTART_PASS"; CANDIDATE_A_STABILIZED="CANDIDATE_A_STABILIZED"; CANDIDATE_A_VERIFIED="CANDIDATE_A_VERIFIED"; CANDIDATE_B_EVIDENCE_COMPLETE="CANDIDATE_B_EVIDENCE_COMPLETE"; CANDIDATE_B_STABILIZED="CANDIDATE_B_STABILIZED"; CANDIDATE_B_SEALED="CANDIDATE_B_SEALED"; A0_B0_PASS="A0_B0_PASS"; ARCHIVE_FINALIZED="ARCHIVE_FINALIZED"; RUNTIME_CONFIG_BOUND="RUNTIME_CONFIG_BOUND"; MAINTENANCE_FRESH="MAINTENANCE_FRESH"; PRE_SWAP_PASS="PRE_SWAP_PASS"; ATOMIC_REPLACED="ATOMIC_REPLACED"; P4_PASS="P4_PASS"; V5_STARTED="V5_STARTED"; V5_READINESS_PASS="V5_READINESS_PASS"; RUNTIME_CONTRACT_PASS="RUNTIME_CONTRACT_PASS"; V5_SCHEMA_PASS="V5_SCHEMA_PASS"; FIRST_API_GATES_PASS="FIRST_API_GATES_PASS"; TRANSACTION_PASS="TRANSACTION_PASS"; LAUNCHER_CANARY_PASS="LAUNCHER_CANARY_PASS"; SCHEMA_RUNTIME_REGRESSION_PASS="SCHEMA_RUNTIME_REGRESSION_PASS"; V3_REGRESSION_PASS="V3_REGRESSION_PASS"; FOCUSED_REGRESSION_PASS="FOCUSED_REGRESSION_PASS"; FULL_REGRESSION_PASS="FULL_REGRESSION_PASS"; AUTOSTART_RESTORED="AUTOSTART_RESTORED"; TASK_RESTART_PASS="TASK_RESTART_PASS"; RESTART_RUNTIME_CONTRACT_PASS="RESTART_RUNTIME_CONTRACT_PASS"; RESTART_API_PASS="RESTART_API_PASS"; INDEPENDENT_AUDIT_PASS="INDEPENDENT_AUDIT_PASS"; PRODUCTION_V5_VERIFIED="PRODUCTION_V5_VERIFIED"; PRE_SWAP_ABORT="PRE_SWAP_ABORT"; ROLLBACK_REQUIRED="ROLLBACK_REQUIRED"; ROLLED_BACK="ROLLED_BACK"; ROLLBACK_FAILED="ROLLBACK_FAILED"; SWAP_STATE_INDETERMINATE="SWAP_STATE_INDETERMINATE"; CONTROLLER_ERROR_BEFORE_MUTATION="CONTROLLER_ERROR_BEFORE_MUTATION"; MANUAL_RECOVERY_REQUIRED="MANUAL_RECOVERY_REQUIRED"
class MutationDisposition(StrEnum): NOT_ATTEMPTED="NOT_ATTEMPTED"; ATTEMPTED_NO_MUTATION_PROVEN="ATTEMPTED_NO_MUTATION_PROVEN"; MUTATED="MUTATED"; INDETERMINATE="INDETERMINATE"
TERMINAL_STATES=frozenset({ControllerState.PRE_SWAP_ABORT,ControllerState.ROLLED_BACK,ControllerState.ROLLBACK_FAILED,ControllerState.PRODUCTION_V5_VERIFIED,ControllerState.SWAP_STATE_INDETERMINATE,ControllerState.CONTROLLER_ERROR_BEFORE_MUTATION,ControllerState.MANUAL_RECOVERY_REQUIRED})
_FLOW=[ControllerState.INIT,ControllerState.ENV_VERIFIED,ControllerState.PREFLIGHT_PASS,ControllerState.LEGACY_VERIFIED,ControllerState.MAINTENANCE_ENTERED,ControllerState.LEGACY_STABILIZED,ControllerState.SOURCE_FROZEN,ControllerState.ARCHIVE_INITIALIZED,ControllerState.CANDIDATE_A_BUILT,ControllerState.CANDIDATE_A_FIRST_PASS,ControllerState.CANDIDATE_A_RESTART_PASS,ControllerState.CANDIDATE_A_STABILIZED,ControllerState.CANDIDATE_A_VERIFIED,ControllerState.CANDIDATE_B_EVIDENCE_COMPLETE,ControllerState.CANDIDATE_B_STABILIZED,ControllerState.CANDIDATE_B_SEALED,ControllerState.A0_B0_PASS,ControllerState.ARCHIVE_FINALIZED,ControllerState.RUNTIME_CONFIG_BOUND,ControllerState.MAINTENANCE_FRESH,ControllerState.PRE_SWAP_PASS,ControllerState.ATOMIC_REPLACED,ControllerState.P4_PASS,ControllerState.V5_STARTED,ControllerState.V5_READINESS_PASS,ControllerState.RUNTIME_CONTRACT_PASS,ControllerState.V5_SCHEMA_PASS,ControllerState.FIRST_API_GATES_PASS,ControllerState.TRANSACTION_PASS,ControllerState.LAUNCHER_CANARY_PASS,ControllerState.SCHEMA_RUNTIME_REGRESSION_PASS,ControllerState.V3_REGRESSION_PASS,ControllerState.FOCUSED_REGRESSION_PASS,ControllerState.FULL_REGRESSION_PASS,ControllerState.AUTOSTART_RESTORED,ControllerState.TASK_RESTART_PASS,ControllerState.RESTART_RUNTIME_CONTRACT_PASS,ControllerState.RESTART_API_PASS,ControllerState.INDEPENDENT_AUDIT_PASS,ControllerState.PRODUCTION_V5_VERIFIED]
LEGAL_TRANSITIONS={s:{_FLOW[i+1]} for i,s in enumerate(_FLOW[:-1])}
for s in _FLOW[:21]: LEGAL_TRANSITIONS[s].add(ControllerState.PRE_SWAP_ABORT)
for s in _FLOW[20:-1]: LEGAL_TRANSITIONS[s].add(ControllerState.ROLLBACK_REQUIRED)
LEGAL_TRANSITIONS[ControllerState.ROLLBACK_REQUIRED]={ControllerState.ROLLED_BACK,ControllerState.ROLLBACK_FAILED,ControllerState.MANUAL_RECOVERY_REQUIRED}
PRE_SWAP_GATES=("administrator","formal_python","branch_head","tests","legacy_baseline","maintenance","port_free","legacy_stabilized","frozen_source","archive_init","candidate_a_first","candidate_a_restart","candidate_a_stabilization","candidate_a_sha","candidate_a_semantic_delta","candidate_b_backend_unopened","candidate_b_b0","candidate_b_semantic_equivalence","candidate_b_checkpoint","candidate_b_delete_mode","candidate_b_wal_absent","candidate_b_shm_absent","candidate_b_stable_samples","candidate_b_handles_closed","candidate_b_rename","candidate_b_sealed","candidate_b_post_seal_opens","archive_5_of_5","archive_all_readonly","runtime_config_this_run","maintenance_freshness","port_fresh","same_volume")

@dataclass(frozen=True)
class ControllerIdentity:
    run_id:str; started_at:str; administrator:bool; formal_python:str; branch:str; head:str; canonical_path:str; initial_runtime_classification:str; production_cutover:bool; controller_version:str=CONTROLLER_VERSION
    def validate(self)->None:
        if not self.run_id.startswith("T03FINAL-") or not all((self.formal_python,self.branch,self.head,self.canonical_path,self.initial_runtime_classification)): raise ControllerError("controller identity incomplete")
@dataclass(frozen=True)
class GateEvidence:
    name:str; passed:bool; run_id:str; checked_at:str; source:str; evidence_path:str; details:Mapping[str,Any]=field(default_factory=dict)
    def validate(self,identity:ControllerIdentity,now:datetime,max_age:int)->None:
        if self.run_id!=identity.run_id or not all((self.name,self.source,self.evidence_path)): raise ControllerError(f"invalid gate evidence: {self.name}")
        try: stamp=datetime.fromisoformat(self.checked_at.replace("Z","+00:00"))
        except ValueError as exc: raise ControllerError(f"malformed gate timestamp: {self.name}") from exc
        if stamp.tzinfo is None or stamp>now+timedelta(seconds=30) or now-stamp>timedelta(seconds=max_age): raise ControllerError(f"stale/future gate evidence: {self.name}")
@dataclass(frozen=True)
class MutationIntent: name:str; status:str="INTENT_PERSISTED"
@dataclass
class ProductionOperations: call:Callable[[str],Mapping[str,Any]]; rollback:Callable[[],Mapping[str,Any]]; restore_legacy_if_needed:Callable[[],Mapping[str,Any]]

class ControllerPersistence:
    def __init__(self,path:Path): self.path=path
    def save(self,payload:Mapping[str,Any])->None:
        temp=self.path.with_suffix(".tmp")
        try:
            with temp.open("w",encoding="utf-8",newline="\n") as f: json.dump(payload,f,ensure_ascii=False,indent=2);f.write("\n");f.flush();os.fsync(f.fileno())
            os.replace(temp,self.path)
        except Exception as exc: raise ControllerError(f"controller persistence failed: {exc}") from exc

@dataclass
class T03ProductionController:
    identity:ControllerIdentity; run_root:Path; operations:ProductionOperations; persistence_factory:Callable[[Path],ControllerPersistence]=ControllerPersistence; state:ControllerState=ControllerState.INIT; gates:dict[str,GateEvidence]=field(default_factory=dict); transitions:list[dict[str,Any]]=field(default_factory=list); mutation_intent:MutationIntent|None=None; mutation_status:str="NOT_MUTATED"; production_v5_atomic_replacement_count:int=0; rollback_attempt_count:int=0; rollback_atomic_replacement_count:int=0; failure_reason:str|None=None; terminal_result:str|None=None
    def __post_init__(self)->None:
        self.identity.validate();self.run_root=self.run_root.resolve();
        if self.run_root.exists(): raise ControllerError("controller run root already exists")
        self.run_root.mkdir(parents=True);self.persistence=self.persistence_factory(self.run_root/"CONTROLLER_STATE.json");self._save_or_error()
    def _payload(self)->dict[str,Any]: return {"identity":asdict(self.identity),"state":self.state.value,"transition_history":self.transitions,"gate_evidence":{k:asdict(v) for k,v in self.gates.items()},"mutation_intent":asdict(self.mutation_intent) if self.mutation_intent else None,"mutation_status":self.mutation_status,"production_v5_atomic_replacement_count":self.production_v5_atomic_replacement_count,"rollback_attempt_count":self.rollback_attempt_count,"rollback_atomic_replacement_count":self.rollback_atomic_replacement_count,"failure_reason":self.failure_reason,"terminal_result":self.terminal_result}
    def _save_or_error(self)->None: self.persistence.save(self._payload())
    def transition(self,target:ControllerState,**evidence:Any)->None:
        if self.state in TERMINAL_STATES: raise ControllerError(f"terminal state locked: {self.state}")
        if target not in LEGAL_TRANSITIONS.get(self.state,set()): raise ControllerError(f"illegal transition: {self.state}->{target}")
        self.state=target;self.transitions.append({"at":datetime.now(UTC).isoformat(),"state":target.value,"evidence":evidence});self._save_or_error()
    def require_pre_swap(self,gates:Mapping[str,GateEvidence],now:datetime|None=None)->None:
        now=now or datetime.now(UTC)
        if set(gates)!=set(PRE_SWAP_GATES): raise ControllerError("mandatory gate set mismatch")
        for g in gates.values(): g.validate(self.identity,now,900)
        self.gates=dict(gates);self._save_or_error()
        if not self.identity.production_cutover: self.transition(ControllerState.PRE_SWAP_ABORT,reason="unauthorized");raise ControllerError("production authorization absent")
        if not self.identity.administrator or self.identity.initial_runtime_classification!="LEGACY_V3": self.transition(ControllerState.PRE_SWAP_ABORT,reason="identity");raise ControllerError("identity gate failed")
        failed=[g.name for g in gates.values() if not g.passed]
        if failed: self.transition(ControllerState.PRE_SWAP_ABORT,failed=failed);self.operations.restore_legacy_if_needed();raise ControllerError("pre-swap gates failed")
        self.transition(ControllerState.PRE_SWAP_PASS)
    def _intent(self,name:str)->None: self.mutation_intent=MutationIntent(name);self.mutation_status="INTENT_PERSISTED";self._save_or_error()
    def _rollback(self,reason:str)->None:
        if self.rollback_attempt_count: raise ControllerError("rollback already attempted")
        self.rollback_attempt_count=1;self.transition(ControllerState.ROLLBACK_REQUIRED,reason=reason);self._intent("ROLLBACK_REPLACEMENT")
        try: result=dict(self.operations.rollback())
        except Exception as exc: self.failure_reason=str(exc);self.terminal_result="ROLLBACK_FAILED";self.transition(ControllerState.ROLLBACK_FAILED,reason=self.failure_reason);raise ControllerError(self.failure_reason) from exc
        if result.get("passed") is not True or result.get("verified") is not True: self.failure_reason=str(result);self.terminal_result="ROLLBACK_FAILED";self.transition(ControllerState.ROLLBACK_FAILED,result=result);raise ControllerError("rollback verification failed")
        self.rollback_atomic_replacement_count=1;self.terminal_result="ROLLED_BACK";self.transition(ControllerState.ROLLED_BACK,result=result)
    def atomic_replace(self)->Mapping[str,Any]:
        if self.state!=ControllerState.PRE_SWAP_PASS or self.production_v5_atomic_replacement_count: raise ControllerError("atomic replacement unavailable")
        self._intent("ATOMIC_V5_REPLACEMENT")
        try: result=dict(self.operations.call("ATOMIC_REPLACEMENT"))
        except Exception as exc: self.mutation_status="INDETERMINATE";self._save_or_error();self._rollback("atomic callback exception");raise ControllerError("atomic callback exception") from exc
        try: disposition=MutationDisposition(result["disposition"])
        except Exception: disposition=MutationDisposition.INDETERMINATE
        self.mutation_status=disposition.value;self._save_or_error()
        if disposition in {MutationDisposition.NOT_ATTEMPTED,MutationDisposition.ATTEMPTED_NO_MUTATION_PROVEN}: self.transition(ControllerState.PRE_SWAP_ABORT,result=result);self.operations.restore_legacy_if_needed();raise ControllerError("atomic not mutated")
        self.production_v5_atomic_replacement_count=1;self._save_or_error()
        if disposition is MutationDisposition.INDETERMINATE or result.get("passed") is not True: self.terminal_result="SWAP_STATE_INDETERMINATE";self._rollback("indeterminate atomic state");raise ControllerError("atomic state indeterminate")
        self.transition(ControllerState.ATOMIC_REPLACED,result=result);return result
    def post_swap_gate(self,name:str,next_state:ControllerState)->Mapping[str,Any]:
        if self.state in TERMINAL_STATES or self.state==ControllerState.ROLLBACK_REQUIRED: raise ControllerError("post-swap continuation forbidden")
        if self.production_v5_atomic_replacement_count!=1: raise ControllerError("post-swap gate without one V5 replacement")
        try: result=dict(self.operations.call(name))
        except Exception as exc: self._rollback(f"post-swap callback exception: {name}"); raise ControllerError(str(exc)) from exc
        if result.get("passed") is not True: self._rollback(f"post-swap gate failed: {name}"); raise ControllerError(f"post-swap gate failed: {name}")
        self.transition(next_state,result=result);return result

__all__=["CONTROLLER_VERSION","ControllerError","ControllerIdentity","ControllerPersistence","ControllerState","GateEvidence","LEGAL_TRANSITIONS","MutationDisposition","MutationIntent","PRE_SWAP_GATES","ProductionOperations","T03ProductionController"]
