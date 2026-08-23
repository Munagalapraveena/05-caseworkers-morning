# Architecture Decisions

## 1. Policy enforcement

The agent treats ACA-2026/1 as a binding authority policy.

Actions covered by section 3 are blocked at a policy gate before any protected action can occur.

The system does not attempt a partial or preparatory version of a protected action.

Protected actions result in an escalation record and do not stop processing of other referrals.

## 2. Day-2 amendment

ACA-2026/2 introduces section 3.9, which prohibits drafting a triage note for a household containing a person under 18.

The implementation therefore checks household composition before calling the triage-note generator.

If a person under 18 is found, the referral is handed to a caseworker.

The system does not create a draft and does not classify this as an escalation.

## 3. Unknown household

If household composition cannot be established, the system treats section 3.9 as applicable in accordance with ACA-2026/2 section 5.2 and ACA-2026/1 section 6.1.

The referral is therefore handed to a caseworker rather than producing a triage note.

## 4. Work already completed

The system records trace events as processing occurs.

If a referral is handed off part-way through processing, the work already completed remains available in the execution trace rather than restarting the referral.

## 5. Continue-on-error behaviour

An escalation or handoff for one referral does not stop the processing of other referrals.

Each referral is processed independently.

## 6. What the agent cannot do

The agent has no execution path for:

- changing entitlement or eligibility;
- suspending, terminating, or reinstating awards;
- initiating, altering, or cancelling payments;
- changing payment details;
- sending resident or third-party communications;
- disclosing resident information externally;
- creating protected findings of fact;
- other irreversible actions.

These cases terminate at the policy gate and produce an escalation instead.

## 7. What we cut for time

We deliberately kept the solution as a command-line Python application rather than building a web interface. The problem does not require a user interface, and the CLI is sufficient to demonstrate the complete caseworker workflow.

We also did not add an external LLM dependency. The supplied policy is deterministic and safety-critical, so the policy gate is implemented explicitly rather than relying on a language model to decide whether a protected action is permitted.

## 8. What the solution does not do

The agent does not actually change resident cases, payments, entitlement, or eligibility.

It only reads the supplied referral and history data, produces permitted drafts, records trace information, hands ordinary restricted casework to a human, or escalates protected actions.

## 9. What I would improve first

The first improvement would be a more structured policy configuration so that future policy amendments can be added without changing the core processing flow.

A second improvement would be a richer supervisor handoff view showing the referral summary, requested action, retrieved history, policy provision, and completed processing steps in one place.
