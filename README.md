# Muse–ChatGPT Setup

ชุดติดตั้ง Python บน Mac สำหรับส่ง Handoff ที่ตรวจสอบได้ระหว่าง ChatGPT และ Muse พร้อมคู่มือภาษาไทย ตัวอย่างค่าตั้ง และชุดทดสอบ

## เริ่มต้น

อ่าน [คู่มือติดตั้งภาษาไทย](START_HERE_TH.md) หรือเปิด [คู่มือ HTML](START_HERE_TH.html) ในเบราว์เซอร์ แล้วเริ่มด้วยการทดสอบ local/dry-run ก่อนเชื่อม Google Drive จริง

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-oauth.txt
python -m unittest discover -s . -p 'test_*.py' -v
python verify_package.py
```

จากนั้นคัดลอก deployment.example.json เป็น deployment.user.json กรอก Drive IDs และพาธของเครื่องผู้ติดตั้งเอง แล้วทำตามคู่มือ prepare_install.py จะสร้างค่าตั้งในเครื่องเท่านั้น ยังไม่เปิดอัปโหลด ไม่โหลด launchd และไม่อนุมัติสิทธิ์แทนผู้ใช้

## องค์ประกอบ

- uploader.py / scheduled_upload.py — ตรวจ schema v2, unique ID, SHA-256, duplicate/no-overwrite, upload และ read-back
- capture_session.py / capture_batch.py — ค้นทุกแชต ChatGPT ที่เข้าถึงได้ทั้ง active/archived ใหม่ทุกรอบ เก็บข้อความวันนี้/เมื่อวานโดยไม่ล็อกรายชื่อ ต้องมีเครื่องมืออ่านแชตจริง
- daily_pipeline.py — ใช้หลักฐานจาก Session Summary สร้าง Handoff ผ่าน Codex CLI
- check_muse.py / checkpoint_writer.py — ตรวจสถานะ และบันทึกหลักฐานโดยไม่อนุมัติ finalize
- prepare_install.py / deployment_admin.py / manage_launchd.py — ตั้งค่าบัญชีและงานบนเครื่องผู้ติดตั้ง
- CHATGPT_CAPTURE_PROMPT.md / MUSE_LEDGER_ADDENDUM_TEMPLATE.md — แม่แบบประสานงานในแอป

## ตารางเริ่มต้น (JST)

เก็บแชต 19:30 → ส่ง Handoff 20:00 → Muse รับ/ตรวจซ้ำ 20:30, 21:00, 21:30 → finalize หรือ incomplete 21:40 → context 21:45 → Daily Brief 22:00 ส่วน weekly review อาทิตย์ 23:15

เป็น schedule amendment วันที่ 11 พ.ย. 2026 ต้องตั้งงาน Muse และงานเก็บแชตแยกตามคู่มือ Python ไม่สามารถตั้งงานหรืออ่านข้อความทุกบัญชีแทนเจ้าของบัญชีได้

Handoff ที่ daily_pipeline.py สร้างใช้ ID `chatgpt-<event_date>-<32 hex source fingerprint>`; Muse ต้องตรวจ YAML/ID/hash/registry และไม่ผูกการรับไฟล์กับเวลา HHMM ในชื่อ

## ขอบเขตและผลทดสอบ

ทดสอบ local ผ่าน 137 รายการใน Python 3.13 รวม dry-run, create, duplicate และแตกชุดติดตั้งไปพาธที่มีช่องว่างด้วยค่าตั้งจำลอง ไม่มีการใช้บัญชีใหม่หรือรับรองรอบอัตโนมัติครบวงจร ดู TEST-RESULTS.txt และ PACKAGE-VERIFICATION.json

Repository นี้มีเฉพาะต้นฉบับสำหรับติดตั้งและข้อมูลตัวอย่าง ไม่รวม credentials/token, Drive IDs จริง, ข้อมูลแชตจริง, Daily Log/Memory หรือ runtime ของเครื่องเดิม ไฟล์เหล่านี้ต้องสร้างในเครื่องผู้ติดตั้งเองและอยู่ใน .gitignore

Python อยู่บน Mac ไม่เพิ่ม Python service บน Muse VM การส่งข้อมูลกลับเข้าแต่ละแชต ChatGPT อัตโนมัติยังไม่รวมในชุดนี้

โหมดเก็บต้นทางเริ่มต้นล่าสุด: `capture_mode: all_accessible` ไม่ต้องใส่รายชื่อแชตเอง แชตเก่าที่ไม่อัปเดตจะนับเฉพาะ metadata; ข้อความที่ถูกตัดและแชตที่อ่านไม่ได้ทำให้รายงาน partial ไม่ถือว่าประวัติทั้งบัญชีครบ หากต้องการจำกัดข้อมูลสำหรับบัญชีอื่นเลือก allowlist ได้ ดู CHATGPT_CAPTURE_PROMPT.md ก่อนอนุญาตส่งข้อมูลจากทุกหัวข้อเข้า Drive
