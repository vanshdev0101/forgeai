"""Synthesize the two demo document sets (committed, with this script and prompts/synth_doc.md).

    python demos/synthesize.py            # writes demos/hr and demos/spares

The facts are fixed here in code; the factory model only writes the prose around them, and every fact is
then checked to appear verbatim (missing ones are appended in a "Key figures" section), so the documents
contain exactly the figures listed below. The spare-parts catalogue is generated in code with a fixed seed.
PDFs are rendered with md2pdf (python-markdown + headless Chrome) when available.
"""
import csv
import random
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from factory.common import ask_json, log  # noqa: E402
from factory.facts import fact_in_text  # noqa: E402

COMPANY = "Meridian Ship Management, a ship-management company with shore offices in Mumbai and Singapore"

HR_DOCS = {
    "leave_policy": ("Shore Staff Leave Policy", "how much leave shore staff get and how to apply", [
        "Annual leave by grade: G1 Associate 18 days, G2 Senior Associate 21 days, G3 Manager 24 days, "
        "G4 Senior Manager 27 days, G5 Director 30 days",
        "annual leave accrues monthly at one twelfth of the yearly entitlement",
        "up to 10 days of unused annual leave may be carried into the next calendar year",
        "carried-over leave above 10 days lapses on 31 December",
        "12 days of paid sick leave per calendar year",
        "a medical certificate is required for sick leave longer than 2 consecutive working days",
        "26 weeks of paid maternity leave",
        "10 working days of paid paternity leave, to be taken within 3 months of the birth",
        "5 days of paid bereavement leave for an immediate family member",
        "annual leave requests must be submitted at least 14 days in advance",
        "emergency leave may be applied for retrospectively within 3 working days of returning",
        "the reporting manager approves or rejects leave requests within 5 working days",
    ]),
    "travel_expense_policy": ("Business Travel and Expense Policy", "what staff may spend and claim on work trips", [
        "daily allowance of INR 2,500 for domestic travel",
        "daily allowance of USD 90 for international travel",
        "hotel limit of INR 7,000 per night in metro cities and INR 4,500 per night elsewhere in India",
        "economy class for flights under 6 hours",
        "premium economy for flights of 6 hours or longer, with Head of Department approval",
        "use of a personal car is reimbursed at INR 12 per km",
        "expense claims must be filed within 30 days of returning",
        "original receipts are required for any single expense above INR 500",
        "claims filed after 30 days need Finance Director approval",
    ]),
    "remote_work_conduct_policy": ("Remote Work and Code of Conduct", "where and how staff may work, and conduct rules", [
        "up to 2 days of remote work per week, with the reporting manager's approval",
        "core hours are 10:00 to 16:00 IST",
        "a home-office equipment allowance of INR 15,000 once every 3 years",
        "gifts above INR 2,000 must be declared to HR",
        "conflicts of interest must be declared within 7 days of becoming aware of them",
        "harassment complaints go to the Internal Committee within 3 months of the incident",
        "the confidential ethics hotline is open 24 hours a day",
    ]),
}

SUPPLIERS = {
    "nordic_marine_supply_terms": ("Nordic Marine Supply: Terms of Supply", "Nordic Marine Supply (Rotterdam)", [
        "payment terms are Net 30 days from invoice",
        "a 5% volume discount applies to orders above USD 10,000",
        "an 8% volume discount applies to orders above USD 25,000",
        "items in stock ship within 3 working days",
        "urgent air freight adds a 15% surcharge on the order value",
        "delivery terms are DAP to the vessel's port",
        "parts carry a 12-month warranty",
        "returns are accepted within 30 days with a 10% restocking fee",
    ]),
    "asia_pacific_ship_parts_terms": ("Asia Pacific Ship Parts: Terms of Supply", "Asia Pacific Ship Parts (Singapore)", [
        "50% advance payment, balance on delivery",
        "a 3% discount applies to orders above USD 5,000",
        "items in stock ship within 2 working days",
        "urgent air freight adds a 20% surcharge on the order value",
        "delivery terms are CIF Singapore",
        "parts carry a 6-month warranty",
        "returns are accepted within 14 days with a 15% restocking fee",
    ]),
}

ENGINES = ["MAN B&W 6S50MC-C", "Wartsila 6L32", "Yanmar 6EY18", "Caterpillar 3512"]
PARTS = [("fuel injector nozzle", "fuel system", 380), ("piston ring set", "piston", 1450),
         ("cylinder liner", "cylinder", 9800), ("exhaust valve spindle", "valves", 3200),
         ("turbocharger bearing", "turbocharger", 2100), ("lube oil filter element", "filters", 95),
         ("fuel oil filter element", "filters", 110), ("cylinder head gasket kit", "gaskets", 640),
         ("cooling water pump seal", "cooling", 420), ("starting air valve", "valves", 1750)]


def catalogue(path):
    rng = random.Random(42)
    rows = []
    for e_i, engine in enumerate(ENGINES):
        for p_i, (part, cat, base) in enumerate(PARTS):
            if rng.random() < 0.15:
                continue
            supplier = "Nordic Marine Supply" if (e_i + p_i) % 2 == 0 else "Asia Pacific Ship Parts"
            stock = rng.choice([0, 0, 2, 4, 6, 10, 24])
            rows.append({
                "part_number": f"{['MBW', 'WRT', 'YAN', 'CAT'][e_i]}-{p_i + 1:02d}{rng.randint(10, 99)}",
                "description": part, "category": cat, "compatible_engine": engine,
                "unit_price_usd": round(base * rng.uniform(0.8, 1.3), 2), "stock_qty": stock,
                "supplier": supplier, "lead_time_days": 0 if stock else rng.choice([14, 21, 28, 42]),
                "min_order_qty": rng.choice([1, 1, 2, 4]),
            })
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def write_doc(out_dir, name, title, audience, purpose, facts):
    o = ask_json("synth_doc", check=lambda o: None if isinstance(o, dict) and isinstance(o.get("markdown"), str)
                 and len(o["markdown"].split()) > 200 else 'need {"markdown": "<document of 500-800 words>"}',
                 temperature=0.4, company=COMPANY, title=title, audience=audience, purpose=purpose,
                 facts="\n".join(f"- {f}" for f in facts))
    md = o["markdown"].strip()
    missing = [f for f in facts if not fact_in_text(f, md)]
    if missing:  # keep the documents exactly as specified, whatever the model dropped
        md += "\n\n## Key figures\n\n" + "\n".join(f"- {f[0].upper() + f[1:]}." for f in missing)
    src = out_dir / "source" / f"{name}.md"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(md + "\n")
    docs = out_dir / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    md2pdf = shutil.which("md2pdf") or str(Path.home() / ".local/bin/md2pdf")
    if Path(md2pdf).exists():
        subprocess.run([md2pdf, str(src), str(docs / f"{name}.pdf")], check=True, capture_output=True)
    else:
        shutil.copy(src, docs / f"{name}.md")
    log(f"synth: {name}: {len(md.split())} words, {len(missing)} fact(s) appended")
    return {"name": name, "words": len(md.split()), "facts": len(facts), "appended": missing}


def main():
    manifest = {"hr": [], "spares": []}
    hr = ROOT / "demos" / "hr"
    for name, (title, purpose, facts) in HR_DOCS.items():
        manifest["hr"].append(write_doc(hr, name, title, "shore staff of all grades", purpose, facts))
    (hr / "brief.txt").write_text("I need an assistant that answers HR policy questions for shore staff.\n")

    sp = ROOT / "demos" / "spares"
    (sp / "docs").mkdir(parents=True, exist_ok=True)
    n = catalogue(sp / "docs" / "spare_parts_catalogue.csv")
    log(f"synth: catalogue: {n} parts")
    for name, (title, supplier, facts) in SUPPLIERS.items():
        manifest["spares"].append(write_doc(sp, name, title, "vessel superintendents and purchasing staff",
                                            f"the commercial terms of {supplier} for ship spare parts", facts))
    (sp / "brief.txt").write_text(
        "I need an assistant that helps vessel superintendents find ship spare parts for our main and auxiliary "
        "engines, check prices, stock and lead times, and compare supplier terms before raising a purchase "
        "request.\n")
    import json
    (ROOT / "demos" / "synthesis_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
