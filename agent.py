import json
import urllib.request
import urllib.error
from datetime import date
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

QUEUE_FILE = BASE_DIR / "referral-queue.json"

HISTORY_API = "http://127.0.0.1:8083"


# ============================================================
# TRACE LOGGER
# ============================================================

class Trace:
    def __init__(self):
        self.events = []

    def log(self, referral_id, step, message, **details):
        event = {
            "referral_id": referral_id,
            "step": step,
            "message": message,
            "details": details
        }

        self.events.append(event)

        print(
            f"[{referral_id}] "
            f"[{step}] "
            f"{message}"
        )

        if details:
            for key, value in details.items():
                print(f"    {key}: {value}")


# ============================================================
# HISTORY API CLIENT
# ============================================================

class HistoryAPI:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")

    def get_json(self, path):
        url = self.base_url + path

        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))

        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"History API returned HTTP {exc.code} for {url}"
            )

        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Could not connect to History API: {exc}"
            )

    def get_resident(self, resident_ref):
        return self.get_json(
            f"/residents/{resident_ref}"
        )

    def get_household(self, resident_ref):
        return self.get_json(
            f"/residents/{resident_ref}/household"
        )

    def get_events(self, resident_ref):
        return self.get_json(
            f"/residents/{resident_ref}/events"
        )

    def health(self):
        return self.get_json("/health")


# ============================================================
# POLICY ENGINE
# ============================================================

class PolicyEngine:

    # Actions that clearly fall under section 3
    PROTECTED_ACTIONS = [
        {
            "keywords": ["suspend"],
            "policy": "ACA-2026/1 section 3.2",
            "reason": "Suspension of an award requires supervisor approval."
        },
        {
            "keywords": ["terminate"],
            "policy": "ACA-2026/1 section 3.2",
            "reason": "Termination of an award requires supervisor approval."
        },
        {
            "keywords": ["reinstate"],
            "policy": "ACA-2026/1 section 3.2",
            "reason": "Reinstatement of an award requires supervisor approval."
        },
        {
            "keywords": ["payment details", "bank details", "card details"],
            "policy": "ACA-2026/1 section 3.4",
            "reason": "Changing payment details requires supervisor approval."
        },
        {
            "keywords": ["initiate payment", "make payment", "cancel payment"],
            "policy": "ACA-2026/1 section 3.3",
            "reason": "Changing or initiating a payment requires supervisor approval."
        },
        {
            "keywords": ["send communication", "contact resident", "contact third party"],
            "policy": "ACA-2026/1 section 3.5",
            "reason": "Sending communication requires supervisor approval."
        }
    ]

    def check_protected_action(self, requested_action):
        action = requested_action.lower().strip()

        for rule in self.PROTECTED_ACTIONS:
            for keyword in rule["keywords"]:
                if keyword in action:
                    return {
                        "protected": True,
                        "policy": rule["policy"],
                        "reason": rule["reason"]
                    }

        return {
            "protected": False
        }


# ============================================================
# AGE / HOUSEHOLD CHECK
# ============================================================

def calculate_age(date_of_birth, as_of):
    dob = date.fromisoformat(date_of_birth)

    age = (
        as_of.year
        - dob.year
        - ((as_of.month, as_of.day) < (dob.month, dob.day))
    )

    return age


def find_children(household, as_of):
    children = []

    for person in household:

        try:
            age = calculate_age(
                person["date_of_birth"],
                as_of
            )

        except Exception:
            # If age cannot be established safely,
            # treat the household as requiring handoff.
            children.append({
                "name": person.get("name", "Unknown"),
                "age": None,
                "reason": "Age could not be established."
            })
            continue

        if age < 18:
            children.append({
                "name": person.get("name", "Unknown"),
                "age": age,
                "date_of_birth": person.get("date_of_birth")
            })

    return children


# ============================================================
# TRIAGE NOTE
# ============================================================

def create_triage_note(referral, resident, household, events):

    recent_events = events[-3:] if events else []

    event_summary = []

    for event in recent_events:
        event_summary.append(
            f"{event.get('date')}: "
            f"{event.get('type')} — "
            f"{event.get('detail')}"
        )

    if not event_summary:
        event_summary.append("No case events available.")

    note = f"""
TRIAGE NOTE — {referral['referral_id']}

Resident:
{referral['resident_ref']}

Referral source:
{referral['source']}

Summary:
{referral['summary']}

Requested action:
{referral['requested_action']}

Urgency:
{referral['urgency']}

Current case status:
{resident.get('status', 'Unknown')}

Benefit:
{resident.get('benefit_code', 'Unknown')}

District:
{resident.get('district', 'Unknown')}

Household size:
{len(household)}

Recent case events:
- {"\n- ".join(event_summary)}

Recommended next step:
Caseworker review of the referral and supporting history.

This is a DRAFT only.
It does not change the resident's case.
"""

    return note.strip()


# ============================================================
# PROCESS ONE REFERRAL
# ============================================================

def process_referral(referral, api, policy, trace):

    referral_id = referral["referral_id"]
    resident_ref = referral["resident_ref"]

    print()
    print("=" * 70)
    print(referral_id)
    print("=" * 70)

    # --------------------------------------------------------
    # STEP 1: Read referral
    # --------------------------------------------------------

    trace.log(
        referral_id,
        "READ_REFERRAL",
        "Referral read.",
        resident_ref=resident_ref,
        requested_action=referral["requested_action"]
    )

    # --------------------------------------------------------
    # STEP 2: Retrieve resident history
    # --------------------------------------------------------

    try:
        resident = api.get_resident(resident_ref)

    except RuntimeError as exc:

        trace.log(
            referral_id,
            "HISTORY_ERROR",
            "Could not retrieve resident history.",
            error=str(exc)
        )

        return {
            "referral_id": referral_id,
            "outcome": "HANDOFF",
            "reason": "Resident history could not be established."
        }

    trace.log(
        referral_id,
        "HISTORY",
        "Resident history retrieved.",
        status=resident.get("status"),
        district=resident.get("district")
    )

    # --------------------------------------------------------
    # STEP 3: Retrieve household
    # --------------------------------------------------------

    try:
        household_response = api.get_household(resident_ref)
        household = household_response["household"]

    except Exception as exc:

        trace.log(
            referral_id,
            "HOUSEHOLD_ERROR",
            "Household composition could not be established.",
            error=str(exc)
        )

        # ACA-2026/2 section 5.2:
        # unknown household => 3.9 applies
        trace.log(
            referral_id,
            "HANDOFF",
            "Household unknown; treating child restriction as applicable.",
            policy="ACA-2026/2 section 5.2"
        )

        return {
            "referral_id": referral_id,
            "outcome": "HANDOFF",
            "reason": "Household composition could not be established."
        }

    trace.log(
        referral_id,
        "HOUSEHOLD",
        "Household composition retrieved.",
        household_size=len(household)
    )

    # --------------------------------------------------------
    # STEP 4: Check protected action FIRST
    # --------------------------------------------------------

    protected = policy.check_protected_action(
        referral["requested_action"]
    )

    if protected["protected"]:

        trace.log(
            referral_id,
            "POLICY_GATE",
            "Protected action detected.",
            policy=protected["policy"],
            reason=protected["reason"]
        )

        # HARD STOP.
        #
        # We do NOT perform the requested action.
        # We do NOT perform a partial version.
        # We do NOT create a fake approval.
        #

        trace.log(
            referral_id,
            "ESCALATE",
            "Action blocked. Supervisor approval is required.",
            policy=protected["policy"]
        )

        return {
            "referral_id": referral_id,
            "outcome": "ESCALATE",
            "policy": protected["policy"],
            "reason": protected["reason"]
        }

    # --------------------------------------------------------
    # STEP 5: Day-2 surprise amendment
    # --------------------------------------------------------

    received_date = date.fromisoformat(
        referral["received_at"][:10]
    )

    children = find_children(
        household,
        received_date
    )

    if children:

        child_names = [
            child["name"]
            for child in children
        ]

        trace.log(
            referral_id,
            "DAY2_GUARDRAIL",
            "Household contains a person under 18.",
            policy="ACA-2026/2 section 3.9",
            children=child_names
        )

        # IMPORTANT:
        #
        # We DO NOT call create_triage_note().
        #
        # The amendment prohibits the draft itself.

        trace.log(
            referral_id,
            "HANDOFF",
            "Triage note NOT drafted. Referral handed to caseworker.",
            policy="ACA-2026/2 section 3.9"
        )

        return {
            "referral_id": referral_id,
            "outcome": "HANDOFF",
            "policy": "ACA-2026/2 section 3.9",
            "children": children,
            "reason": (
                "Household includes a person under 18. "
                "A human caseworker must perform the ordinary casework."
            )
        }

    # --------------------------------------------------------
    # STEP 6: Retrieve events
    # --------------------------------------------------------

    try:
        events_response = api.get_events(resident_ref)
        events = events_response["events"]

    except Exception as exc:

        trace.log(
            referral_id,
            "EVENT_ERROR",
            "Case events could not be retrieved.",
            error=str(exc)
        )

        return {
            "referral_id": referral_id,
            "outcome": "HANDOFF",
            "reason": "Case events could not be established."
        }

    trace.log(
        referral_id,
        "EVENTS",
        "Case events retrieved.",
        event_count=len(events)
    )

    # --------------------------------------------------------
    # STEP 7: Draft triage note
    # --------------------------------------------------------

    note = create_triage_note(
        referral,
        resident,
        household,
        events
    )

    trace.log(
        referral_id,
        "DRAFT",
        "Triage note drafted for caseworker review."
    )

    return {
        "referral_id": referral_id,
        "outcome": "DRAFT",
        "triage_note": note
    }


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 70)
    print("CALDER COUNTY — CASEWORKER MORNING AGENT")
    print("ACA-2026/1 + ACA-2026/2")
    print("=" * 70)

    # --------------------------------------------------------
    # Load queue
    # --------------------------------------------------------

    with open(
        QUEUE_FILE,
        "r",
        encoding="utf-8"
    ) as file:
        referrals = json.load(file)

    print(f"\nLoaded {len(referrals)} referrals.")

    # --------------------------------------------------------
    # Connect to history service
    # --------------------------------------------------------

    api = HistoryAPI(HISTORY_API)

    try:
        health = api.health()

        print(
            f"History API: {health['status']} "
            f"({health['records']} residents)"
        )

    except Exception as exc:

        print()
        print("ERROR: History API is not running.")
        print()
        print("Start it in another PowerShell window with:")
        print()
        print(
            "python services\\history_service.py --port 8083"
        )
        print()
        print(f"Details: {exc}")
        return

    policy = PolicyEngine()
    trace = Trace()

    results = []

    # --------------------------------------------------------
    # Process every referral
    # --------------------------------------------------------

    for referral in referrals:

        try:
            result = process_referral(
                referral,
                api,
                policy,
                trace
            )

        except Exception as exc:

            referral_id = referral["referral_id"]

            trace.log(
                referral_id,
                "UNEXPECTED_ERROR",
                "Referral could not be completed.",
                error=str(exc)
            )

            result = {
                "referral_id": referral_id,
                "outcome": "HANDOFF",
                "reason": "Unexpected processing error."
            }

        results.append(result)

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print()
    print()
    print("=" * 70)
    print("FINAL RUN SUMMARY")
    print("=" * 70)

    counts = {
        "DRAFT": 0,
        "HANDOFF": 0,
        "ESCALATE": 0
    }

    for result in results:

        outcome = result["outcome"]

        if outcome in counts:
            counts[outcome] += 1

        print(
            f"{result['referral_id']}: "
            f"{outcome}"
        )

    print()
    print(f"Drafts:    {counts['DRAFT']}")
    print(f"Handoffs:  {counts['HANDOFF']}")
    print(f"Escalations: {counts['ESCALATE']}")

    # --------------------------------------------------------
    # Save machine-readable trace
    # --------------------------------------------------------

    trace_file = BASE_DIR / "run-trace.json"

    with open(
        trace_file,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            {
                "policy": [
                    "ACA-2026/1",
                    "ACA-2026/2"
                ],
                "referrals_processed": len(referrals),
                "results": results,
                "trace": trace.events
            },
            file,
            indent=2
        )

    print()
    print(f"Trace saved to: {trace_file}")
    print()
    print("RUN COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()