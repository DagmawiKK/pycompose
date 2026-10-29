------------------------- MODULE MailboxTrace -------------------------
(***************************************************************************)
(* Trace validation: does a recorded run of the host behave as Mailbox     *)
(* allows?                                                                 *)
(*                                                                         *)
(* Each trace lists what the host posted, what reached Python, and when    *)
(* the host pulled. Every logged event must be taken by the model step it  *)
(* names; the steps a log cannot see (taking a batch, publishing) happen   *)
(* only where the next event needs them. No step leaves a choice, so a     *)
(* run the model cannot follow stops early, and TLC reports a deadlock     *)
(* naming the trace and the event.                                         *)
(*                                                                         *)
(* TraceData, written by trace.py, defines Traces and the constants each   *)
(* run's widgets, values and intents need.                                 *)
(***************************************************************************)
EXTENDS Mailbox, TraceData

VARIABLES t, l   \* the trace being followed, and its next event

E == Traces[t][l]

Pending == l <= Len(Traces[t])

Message(e) ==
    IF e.kind = "report"
    THEN Head(batch).kind = "report" /\ Head(batch).w = e.w /\ Head(batch).v = e.v
    ELSE Head(batch).kind = "intent" /\ Head(batch).id = e.id

TraceInit == Init /\ t \in DOMAIN Traces /\ l = 1

Logged ==
    /\ Pending
    /\ l' = l + 1
    /\ UNCHANGED t
    /\ \/ E.event = "post" /\ E.kind = "report" /\ PostReport(E.w, E.v)
       \/ E.event = "post" /\ E.kind = "intent" /\ PostIntent(E.id)
       \/ E.event = "process" /\ batch # <<>> /\ Message(E) /\ Process
       \/ /\ E.event = "pull" /\ batch = <<>> /\ ~dirty
          /\ IF hostSerial < slot.serial THEN HostPull ELSE UNCHANGED vars

Unlogged ==
    /\ Pending
    /\ UNCHANGED <<t, l>>
    /\ \/ E.event = "process" /\ Take
       \/ E.event = "pull" /\ Publish

\* A finished trace stays where it is, so only a rejected one deadlocks.
Done == ~Pending /\ UNCHANGED <<vars, t, l>>

TraceNext == Logged \/ Unlogged \/ Done
=============================================================================
