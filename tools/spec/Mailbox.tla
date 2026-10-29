---------------------------- MODULE Mailbox ----------------------------
(***************************************************************************)
(* The protocol between the host and the Python loop thread.               *)
(*                                                                         *)
(* The host posts widget reports and intents into one mailbox. The       *)
(* worker takes everything queued as one batch and hands it to the loop   *)
(* thread, the only writer of app state, which applies it in order; once  *)
(* the batch is done one immutable snapshot is published into a slot. The *)
(* host pulls whichever snapshot the slot holds.                           *)
(*                                                                         *)
(* Admission: an intent is never dropped. A widget report drops an earlier *)
(* report for the same widget, and takes its own place at the end, only   *)
(* within the run of messages after the last queued intent, so collapsing *)
(* never moves a value past an intent that should have seen it, and the   *)
(* mailbox stays bounded. A taken batch is never collapsed into.           *)
(***************************************************************************)
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS Widgets, Values, Intents, MaxReports

NoValue == "none"

VARIABLES
    mailbox,        \* messages posted by the host, not yet taken
    batch,          \* messages taken together, not yet applied by the loop
    hostValues,     \* each widget's latest value as the host knows it
    hostSeq,        \* each widget's report sequence number, host side
    reportsPosted,  \* how many reports the host has posted (bounds the model)
    intentsPosted,  \* intents the host has posted
    state,          \* app state on the loop thread: each widget's value
    echo,           \* each widget's latest applied report sequence number
    processed,      \* intents the loop has handled
    bad,            \* TRUE once an intent ran against values it should not see
    dirty,          \* the loop changed state since its last publication
    slot,           \* the published snapshot: its serial and state
    hostSerial,     \* the serial of the snapshot the host holds
    hostSeen        \* the state in the snapshot the host holds

vars == <<mailbox, batch, hostValues, hostSeq, reportsPosted, intentsPosted, state,
          echo, processed, bad, dirty, slot, hostSerial, hostSeen>>

Report(w, v, s) == [kind |-> "report", w |-> w, v |-> v, seq |-> s]
Intent(i, e) == [kind |-> "intent", id |-> i, expect |-> e]

Unset == [w \in Widgets |-> NoValue]

LastIntent ==
    LET at == {i \in 1..Len(mailbox) : mailbox[i].kind = "intent"}
    IN IF at = {} THEN 0 ELSE CHOOSE i \in at : \A j \in at : j <= i

Queued == mailbox \o batch

QueuedIntents == {Queued[i].id : i \in {j \in 1..Len(Queued) : Queued[j].kind = "intent"}}

Without(s, i) == SubSeq(s, 1, i - 1) \o SubSeq(s, i + 1, Len(s))

QueuedReports(w) == {i \in 1..Len(mailbox) : mailbox[i].kind = "report" /\ mailbox[i].w = w}

Init ==
    /\ mailbox = <<>>
    /\ batch = <<>>
    /\ hostValues = Unset
    /\ hostSeq = [w \in Widgets |-> 0]
    /\ reportsPosted = 0
    /\ intentsPosted = {}
    /\ state = Unset
    /\ echo = [w \in Widgets |-> 0]
    /\ processed = {}
    /\ bad = FALSE
    /\ dirty = FALSE
    /\ slot = [serial |-> 0, state |-> Unset]
    /\ hostSerial = 0
    /\ hostSeen = Unset

\* The host reports a widget's settled value.
PostReport(w, v) ==
    /\ reportsPosted < MaxReports
    /\ LET s == hostSeq[w] + 1
           tail == {i \in QueuedReports(w) : i > LastIntent}
       IN /\ mailbox' = IF tail = {}
                        THEN Append(mailbox, Report(w, v, s))
                        ELSE Append(Without(mailbox, CHOOSE i \in tail : TRUE),
                                    Report(w, v, s))
          /\ hostSeq' = [hostSeq EXCEPT ![w] = s]
    /\ hostValues' = [hostValues EXCEPT ![w] = v]
    /\ reportsPosted' = reportsPosted + 1
    /\ UNCHANGED <<batch, intentsPosted, state, echo, processed, bad, dirty, slot,
                   hostSerial, hostSeen>>

\* The host posts an intent; it carries what the user saw for every widget.
PostIntent(i) ==
    /\ i \notin intentsPosted
    /\ mailbox' = Append(mailbox, Intent(i, hostValues))
    /\ intentsPosted' = intentsPosted \cup {i}
    /\ UNCHANGED <<batch, hostValues, hostSeq, reportsPosted, state, echo,
                   processed, bad, dirty, slot, hostSerial, hostSeen>>

\* The worker takes everything queued, once the last batch is applied.
Take ==
    /\ batch = <<>>
    /\ mailbox # <<>>
    /\ batch' = mailbox
    /\ mailbox' = <<>>
    /\ UNCHANGED <<hostValues, hostSeq, reportsPosted, intentsPosted, state,
                   echo, processed, bad, dirty, slot, hostSerial, hostSeen>>

\* The loop thread applies the batch's oldest message.
Process ==
    /\ batch # <<>>
    /\ LET m == Head(batch) IN
         IF m.kind = "report"
         THEN /\ state' = [state EXCEPT ![m.w] = m.v]
              /\ echo' = [echo EXCEPT ![m.w] = m.seq]
              /\ UNCHANGED <<processed, bad>>
         ELSE /\ processed' = processed \cup {m.id}
              /\ bad' = (bad \/ state # m.expect)
              /\ UNCHANGED <<state, echo>>
    /\ batch' = Tail(batch)
    /\ dirty' = TRUE
    /\ UNCHANGED <<mailbox, hostValues, hostSeq, reportsPosted, intentsPosted, slot,
                   hostSerial, hostSeen>>

\* Once a batch is applied, the loop publishes one snapshot.
Publish ==
    /\ dirty
    /\ batch = <<>>
    /\ slot' = [serial |-> slot.serial + 1, state |-> state]
    /\ dirty' = FALSE
    /\ UNCHANGED <<mailbox, batch, hostValues, hostSeq, reportsPosted, intentsPosted,
                   state, echo, processed, bad, hostSerial, hostSeen>>

\* The host pulls the slot whenever it holds something newer.
HostPull ==
    /\ hostSerial < slot.serial
    /\ hostSerial' = slot.serial
    /\ hostSeen' = slot.state
    /\ UNCHANGED <<mailbox, batch, hostValues, hostSeq, reportsPosted,
                   intentsPosted, state, echo, processed, bad, dirty, slot>>

Next ==
    \/ \E w \in Widgets, v \in Values : PostReport(w, v)
    \/ \E i \in Intents : PostIntent(i)
    \/ Take
    \/ Process
    \/ Publish
    \/ HostPull

\* The host may stop posting at any time; the loop and the pull are fair.
Spec == Init /\ [][Next]_vars /\ WF_vars(Take) /\ WF_vars(Process) /\ WF_vars(Publish) /\ WF_vars(HostPull)

-----------------------------------------------------------------------------
\* Safety

TypeOK ==
    /\ hostSerial \in 0..slot.serial
    /\ processed \subseteq intentsPosted
    /\ bad \in BOOLEAN /\ dirty \in BOOLEAN

\* Intents are never dropped: each posted intent is queued or handled.
IntentsNeverDropped == intentsPosted = processed \cup QueuedIntents

\* An intent observes every report posted before it, and nothing posted after.
ReportsPrecedeIntents == ~bad

\* Collapsing keeps at most one queued report per widget between intents.
MailboxBounded ==
    \A w \in Widgets :
        Cardinality(QueuedReports(w))
            <= Cardinality({i \in 1..Len(mailbox) : mailbox[i].kind = "intent"}) + 1

\* The host never holds a snapshot newer than the one published.
HostNeverAhead == hostSerial <= slot.serial

\* Serials and echoes only move forward.
Monotonic ==
    [][/\ slot'.serial >= slot.serial
       /\ hostSerial' >= hostSerial
       /\ \A w \in Widgets : echo'[w] >= echo[w]]_vars

-----------------------------------------------------------------------------
\* Liveness

\* Every posted intent is eventually handled.
NoLostIntents == <>[](processed = intentsPosted)

\* Once the host stops posting, the host ends up holding the final state, and
\* that state carries every widget's latest reported value.
Converges ==
    <>[](/\ mailbox = <<>>
         /\ batch = <<>>
         /\ ~dirty
         /\ hostSerial = slot.serial
         /\ hostSeen = state
         /\ state = hostValues)
=============================================================================
