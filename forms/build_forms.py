"""Generate the two XLSForms (ODK Collect / KoboToolbox) from the CSV sources here.

    python forms/build_forms.py

Constraints mirror the database check constraints so bad values are stopped on
the phone. Arabic is the default language; English is the second.
"""

import csv
import pathlib

from openpyxl import Workbook

HERE = pathlib.Path(__file__).parent
EN, AR = "label::English (en)", "label::Arabic (ar)"
CM_EN, CM_AR = "constraint_message::English (en)", "constraint_message::Arabic (ar)"
SURVEY_COLS = ["type", "name", EN, AR, "required", "constraint", CM_EN, CM_AR, "relevant", "default", "appearance", "hint"]
CHOICE_COLS = ["list_name", "name", EN, AR]

SPECIES = [("cattle", "Cattle", "أبقار"), ("sheep", "Sheep", "أغنام"), ("goats", "Goats", "ماعز"),
           ("camels", "Camels", "جمال"), ("other", "Other", "أخرى")]
DIRECTION = [("north", "North", "شمال"), ("south", "South", "جنوب"), ("east", "East", "شرق"),
             ("west", "West", "غرب"), ("stationary", "Stationary / grazing", "متوقف / يرعى")]
CONDITION = [("1", "1 – very poor", "1 – سيئ جدًا"), ("2", "2 – poor", "2 – سيئ"), ("3", "3 – fair", "3 – متوسط"),
             ("4", "4 – good", "4 – جيد"), ("5", "5 – very good", "5 – جيد جدًا")]
ROUTE = [("open", "Open", "مفتوح"), ("restricted", "Restricted", "مقيد"), ("blocked", "Blocked", "مغلق")]


def monitoring_points():
    with open(HERE / "monitoring_points.csv", encoding="utf-8") as f:
        return [(r["code"], r["name_en"], r["name_ar"]) for r in csv.DictReader(f)]


def write(path, title, form_id, survey, choices):
    wb = Workbook()
    ws = wb.active
    ws.title = "survey"
    ws.append(SURVEY_COLS)
    for row in survey:
        ws.append([row.get(c, "") for c in SURVEY_COLS])
    cs = wb.create_sheet("choices")
    cs.append(CHOICE_COLS)
    for list_name, items in choices.items():
        for name, en, ar in items:
            cs.append([list_name, name, en, ar])
    st = wb.create_sheet("settings")
    st.append(["form_title", "form_id", "version", "default_language"])
    st.append([title, form_id, "2026102001", "Arabic (ar)"])
    wb.save(path)


def q(type_, name, en, ar, **kw):
    return {"type": type_, "name": name, EN: en, AR: ar, **kw}


META = [q("start", "start", "", ""), q("end", "end", "", ""), q("today", "today", "", ""), q("deviceid", "deviceid", "", "")]

flow = META + [
    q("select_one monitoring_point", "monitoring_point", "Monitoring point", "نقطة المراقبة", required="yes", appearance="minimal"),
    q("datetime", "observed_at", "Time herd passed", "وقت مرور القطيع", required="yes", default="now()"),
    q("select_one species", "species", "Species", "النوع", required="yes"),
    q("integer", "head_count", "Number of animals", "عدد الحيوانات", required="yes",
      constraint=". >= 1 and . <= 100000", **{CM_EN: "Enter a number from 1 to 100,000", CM_AR: "أدخل رقمًا من 1 إلى 100,000"}),
    q("note", "large_count_note", "Large count: please check the number again.", "عدد كبير: يرجى التحقق من الرقم مرة أخرى.",
      relevant="${head_count} > 5000"),
    q("select_one direction", "direction", "Direction of travel", "اتجاه الحركة", required="yes"),
    q("geopoint", "location", "Your location", "موقعك", required="yes"),
    q("text", "notes", "Notes (optional)", "ملاحظات (اختياري)"),
]
write(HERE / "flow_count.xlsx", "SLEWCIS herd flow count (provisional, pending IOM TTT alignment)", "slewcis_flow_count",
      flow, {"monitoring_point": monitoring_points(), "species": SPECIES, "direction": DIRECTION})

check = META + [
    q("datetime", "observed_at", "Time of observation", "وقت الملاحظة", required="yes", default="now()"),
    q("geopoint", "location", "Location of the site", "موقع الموقع", required="yes"),
    q("select_one condition", "pasture_condition", "Pasture condition", "حالة المراعي", required="yes"),
    q("select_one condition", "water_condition", "Water condition", "حالة المياه", required="yes"),
    q("select_one route", "route_condition", "Route condition", "حالة الطريق", required="yes"),
    q("image", "photo", "Photo of the site", "صورة للموقع", required="yes"),
    q("text", "notes", "Notes (optional)", "ملاحظات (اختياري)"),
]
write(HERE / "field_check.xlsx", "SLEWCIS field check", "slewcis_field_check", check,
      {"condition": CONDITION, "route": ROUTE})
print("wrote forms/flow_count.xlsx and forms/field_check.xlsx")
