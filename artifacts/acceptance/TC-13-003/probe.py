import io, json, zipfile, openpyxl
from app.services.xlsx_writer import create_export_from_questionnaire
from app.services import fallback_export
wb=openpyxl.Workbook(); ws=wb.active; ws.title="S"; ws["A1"]="Q?"; ws["A1"].number_format="0.00%"; ws["B2"]="=TODAY()"; ws["A2"]="Q2?"
b=io.BytesIO(); wb.save(b)
out=create_export_from_questionnaire(b.getvalue(),[{"id":1,"source_location":json.dumps({"sheet":"S","row":1,"col":1})},{"id":2,"source_location":json.dumps({"sheet":"S","row":2,"col":1})}],{1:"=1+1",2:"Yes"})
x=zipfile.ZipFile(io.BytesIO(out)).read("xl/worksheets/sheet1.xml").decode()
w=openpyxl.load_workbook(io.BytesIO(out)).active
print("B1 xml has <f>:", "<f>1+1</f>" in x, "| B1 type:", w["B1"].data_type, "| B1 number_format:", w["B1"].number_format, "| B2 (orig formula) now:", repr(w["B2"].value))
try:
    fallback_export.create_fallback_pack_csv([{"id":1,"text":"q"}],{1:"=1+1"}); print("csv ok")
except Exception as e: print("csv fallback error:", type(e).__name__, e)
