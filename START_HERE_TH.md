# คู่มือติดตั้ง Muse–ChatGPT บน Mac

> เวลาใช้งานล่าสุดตามคำขอ Neo วันที่ 11 พ.ย. 2026: เก็บแชต 19:30 → ส่ง Handoff 20:00 → Muse 20:30/21:00/21:30 → finalize/incomplete 21:40 → context 21:45 → Daily Brief 22:00 JST; weekly review อาทิตย์ 23:15 เดิม เป็น schedule amendment ไม่ใช่การแก้ประวัติหรือเพิ่มสิทธิ์ finalize ข้อมูลหลังรอบเก็บอาจเข้ารอบถัดไป

รุ่นแม่แบบ 2026-11-11 • อ่านไฟล์นี้ก่อนเปิดงานตามเวลา

อัปเดตการเก็บต้นทาง 11 พ.ย. 2026: ค้นรายชื่อทุกแชต ChatGPT ที่เข้าถึงได้ ทั้ง active และ archived โดยไม่ล็อกรายชื่อ เก็บเฉพาะข้อความวันนี้กับเมื่อวานจากแชตที่อัปเดต ไม่ใช่การส่งประวัติเก่าทั้งบัญชีทุกวัน ข้อความที่ถูกตัด/turn ยังไม่จบถูกเว้นและระบุ partial แชตที่อ่านไม่ได้ต้องแสดงใน coverage ไม่ยืนยันว่า temporary/deleted/inaccessible chats ถูกเก็บ


ชุดนี้ประกอบด้วยสคริปต์ Python, ตัวสร้างค่าตั้ง, ตัวจัดการ launchd, ชุดทดสอบ และแม่แบบคำสั่งสำหรับแอปกับ Muse เป็น **ชุดติดตั้งแบบมีขั้นตอน** ไม่ใช่โปรแกรมที่เปิดแล้วเชื่อมทุกบัญชีอัตโนมัติ

ใช้ Drive IDs, OAuth และบัญชีของผู้ติดตั้งเอง ไม่มี credentials/token/ข้อมูลแชตจริงของผู้สร้างชุดนี้ และไม่ได้รับสิทธิ์จากการอนุมัติเดิมของผู้สร้างระบบ

## 1. ระบบนี้ทำอะไร

```text
แชต ChatGPT ทุกหัวข้อที่เข้าถึงได้และอัปเดตในช่วงเก็บ
  → งานในแอปเก็บข้อความจริง 19:30
  → Python บน Mac ส่ง Session Summary เข้า Drive
  → launchd 20:00 เรียก AI ผ่าน Codex CLI ให้เลือกหลักฐาน
  → Python ตรวจ YAML v2 / ID / hash / ไฟล์ซ้ำ แล้วส่ง Handoff
  → Muse รับ ตรวจ และทำ Daily Log ตามกฎของเจ้าของระบบ
  → Python บน Mac อ่านผลจริงและเขียน checkpoint
  → Muse อ่าน checkpoint ประกอบ แล้วอ่านไฟล์จริงซ้ำ
```

Python อยู่บน Mac; ไม่จำเป็นต้องติดตั้ง Python เพิ่มบน VM ของ Muse ขากลับจาก Muse เข้าแต่ละแชต ChatGPT อัตโนมัติ **ไม่ได้รวมอยู่ในชุดนี้และยังไม่ได้พิสูจน์**

มีทางเริ่มสองแบบ:

- **แบบเล็ก:** ใช้ Handoff Markdown จริงที่สร้างไว้แล้ว ให้ Python ตรวจและส่งเอง ไม่ต้องตั้งงานเก็บแชตหรือ AI รวมข้อมูล
- **แบบเต็มตามแม่แบบ:** เพิ่ม Codex CLI, งานเก็บแชตในแอป, launchd และตัวบันทึก checkpoint หลังจากแบบเล็กผ่าน

## 2. สิ่งที่ต้องมี

- macOS และ Python 3.10 ขึ้นไป; ต้นฉบับทดสอบบน Python 3.13
- บัญชี Google ที่เข้าถึง Drive ของระบบ และ Google Cloud project ที่เปิด Drive API
- Desktop OAuth client ของผู้ติดตั้งเอง
- Muse ที่เชื่อม Drive ได้ และมีข้อตกลงว่าทำอะไร/เขียนไฟล์ใดได้
- สำหรับงานรวมด้วย AI: Codex CLI ที่ติดตั้งและล็อกอินได้
- สำหรับเก็บแชตอัตโนมัติ: แอปที่มีเครื่องมืออ่านข้อความแชตจริงและงานตามเวลาในบัญชีนั้น หากไม่มี ให้ใช้ Session Summary แบบ manual-assisted

การทำงานกับไฟล์ในเครื่องผ่านงานตามเวลาของแอปต้องเปิดเครื่องและแอปไว้ ตาม [เอกสารงานตามเวลาของ OpenAI](https://learn.chatgpt.com/docs/automations) ส่วน launchd ต้องมีผู้ใช้ Mac ล็อกอิน เครื่องหลับ/ปิดอาจทำให้งานช้าหรือไม่รันตามเวลาที่ตั้ง ไม่มีตัวปลุกเครื่องในชุดนี้

## 3. เตรียม Drive และข้อตกลง Muse

ชุดนี้เชื่อมกับระบบ Muse ที่เริ่มใช้งานและตรวจโครงสร้างแล้ว ไม่สร้าง Daily Log ปลอมเพื่อใช้เป็นหลักฐานติดตั้ง

โครงสร้างสำคัญ:

```text
Muse-GPT/
  00 Documentation/         ข้อตกลงและ protocol ของเจ้าของระบบ
  01 Daily Log/YYYY/MM/     Daily Log จริงของเดือนที่ใช้งาน
  02 Project Tracker/
  03 Handoff Inbox/
    session_summaries/
    chatgpt_to_muse/
    muse_to_chatgpt/
  04 Shared Memory/
  05 System/
    sync_status.json
    processed_handoffs.json
    revision_backups/
  99 Archive/
```

ยังไม่ต้องสร้าง sync_checkpoints.json เอง ตัวบันทึกบน Mac จะสร้างหลังทดสอบผ่าน ถ้ามี ledger อยู่แล้วจะไม่ยอม adopt/เขียนทับโดยไม่มี ownership journal

ผู้เริ่มระบบใหม่ควรทำ Manual Handoff จากกิจกรรมจริงหนึ่งรอบ ให้ Muse สร้าง Daily Log draft จริง ตรวจเนื้อหาและ source references ก่อน แล้วจึงใช้ file ID ของ log นั้นเป็น `known_log_file_id` สำหรับตัวตรวจรายเดือน ระหว่างยังไม่มี log จริง ให้เริ่มทดสอบ uploader ในเครื่องก่อน และเลื่อนส่วน checker/checkpoint ไว้

ไฟล์ JSON ที่ตัวตรวจรองรับ:

- processed_handoffs.json ต้องมี key `processed_handoffs` เป็น list; แต่ละรายการมี handoff_id และ sha256_muse_computed หรือ sha256 หากยังไม่มีรายการ ใช้ list ว่างได้
- sync_status.json ต้องระบุวันที่จริงและสถานะจริง ไม่คัดตัวอย่าง healthy ไปเป็นผลจริง
- Daily Log ต้องมี YAML เช่น log_id, event_date, status, revision, source_handoffs; ชื่อไฟล์เป็น YYYY-MM-DD.md อยู่ในโฟลเดอร์เดือนที่ตรวจแล้ว

กำหนดผู้เขียน: Mac เขียน Handoff/Session Summary ของฝั่ง ChatGPT และ ledger ของ Mac; Muse เขียน Daily Log/ไฟล์ที่ผู้ใช้อนุมัติตาม protocol เดิม ไม่ให้สองฝั่งแก้ไฟล์เดียวกันโดยไม่มีข้อตกลง

## 4. แตก ZIP และติดตั้ง Python dependencies

เก็บโฟลเดอร์ในตำแหน่งถาวร เช่น Documents อย่าย้ายหลังตั้ง launchd โดยไม่สร้างพาธใหม่

เปิด Terminal แล้วเข้าโฟลเดอร์ที่แตกจริง:

```sh
cd /พาธ/ที่แตก/muse-installation-kit
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-oauth.txt
.venv/bin/python -m unittest discover -s . -p 'test_*.py' -v
```

ชุดติดตั้งนี้มี 137 tests ถ้าติดตั้ง dependencies ไม่ครบหรือ tests ล้มเหลว ให้แก้ก่อนเปิดงานจริง ไม่แก้ตัวตรวจเพื่อให้ข้อมูลผิดผ่าน

ทดสอบ uploader แบบไม่ใช้บัญชี Google:

```sh
.venv/bin/python uploader.py examples/valid-test-handoff.md --config config.local.example.json --backend local
.venv/bin/python uploader.py examples/valid-test-handoff.md --config config.local.example.json --backend local --apply
.venv/bin/python uploader.py examples/valid-test-handoff.md --config config.local.example.json --backend local --apply
```

คาดหวัง would_create → verified → duplicate_verified โดยมีไฟล์ปลายทางชุดเดียว ตัวอย่างนี้เป็น **LOCAL TEST FIXTURE ห้ามอัปโหลดเข้า inbox ของ Muse หรือ session_summaries จริง**

## 5. ติดตั้ง Codex CLI เฉพาะเมื่อใช้ AI รวมสรุป

ติดตั้งตาม [คู่มือ Codex CLI ทางการ](https://learn.chatgpt.com/docs/codex/cli) แล้วตรวจ:

```sh
codex --version
codex login
codex login status
command -v codex
```

นำพาธ executable จากคำสั่งสุดท้ายไปใส่ `codex_cli` ใน deployment ของคุณ ถ้ามี CLI อยู่ใน desktop app ให้ใช้พาธ executable ที่ตรวจว่าเรียกได้จริง ไม่คัดพาธจากเครื่องคนอื่น

ชุดต้นฉบับใช้ CLI 0.167.0-alpha.3.2 และโหมด exec/ephemeral/output-schema/read-only ปิด shell/web search ในขั้นเลือกหลักฐาน CLI รุ่นอื่นต้องตรวจว่า flags เหล่านี้ยังรองรับ การเรียก CLI ใช้ authentication ที่ CLI ตั้งไว้ ไม่ต้องใส่ API key ลง config ของชุดนี้ ดู [non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)

## 6. กรอก deployment ของเครื่องใหม่

```sh
cp deployment.example.json deployment.user.json
```

เปิด deployment.user.json ด้วย text editor แล้วกรอก:

- handoff_folder_id: โฟลเดอร์ chatgpt_to_muse
- session_folder_id: โฟลเดอร์ session_summaries
- system_folder_id: โฟลเดอร์ 05 System
- sync_status_file_id: ไฟล์ sync_status.json
- registry_file_id: ไฟล์ processed_handoffs.json
- known_log_file_id: Daily Log จริงที่ยืนยันแล้วในเดือนที่จะตรวจ
- backup_folder_id: โฟลเดอร์ revision_backups
- log_month: เดือนเดียวกับ known_log เช่น YYYY-MM
- generation_start_date: วันเริ่มรวมสรุปอัตโนมัติในเดือนนั้น วันที่ก่อนหน้านี้จะไม่ถูกสร้าง Handoff ย้อนหลังเอง
- codex_cli: พาธ executable ที่ตรวจแล้ว หรือ null หากใช้เฉพาะ Handoff ที่สร้างไว้เองโดยไม่ใช้ AI รวมสรุป
- capture_mode: ค่าเริ่มต้นแม่แบบล่าสุดคือ `all_accessible` ค้น active/archived ทุกหน้าใหม่ทุกรอบ แล้วอ่านข้อความของวันนี้/เมื่อวานจากแชตที่อัปเดต ไม่ต้องกรอก chat IDs
- capture_allowlist: ใช้เฉพาะเมื่อเลือก capture_mode=`allowlist` เป็นโหมดจำกัดแชตเอง
- source_day_max_bytes: ค่าเริ่มต้น all_accessible คือ 256000 bytes ต่อวัน เกินแล้วหยุดรายงาน ไม่ตัดข้อมูลเงียบ ๆ
- legacy_exception_date / manual_finalize_date: ค่าเริ่มต้น null ไม่คัดข้อยกเว้นหรือการอนุมัติของระบบคนอื่น

Drive folder ID คือส่วนหลัง /folders/ ใน URL; file ID คือส่วนหลัง /file/d/ หรือ /document/d/ ต้องแยก folder กับ file และตรวจชื่อ/บัญชีจริงด้วย ไม่ใช้ชื่ออย่างเดียวเพราะชื่อซ้ำได้

จากนั้น:

```sh
.venv/bin/python prepare_install.py --deployment deployment.user.json
```

สิ่งที่สร้างในเครื่องเท่านั้น:

- deployment.json: ค่าขอบเขตของการติดตั้งนี้
- .private/config.json: ปลายทางและสถานะเปิดส่งจริง เริ่มต้นปิด
- .private/schedule-settings.json: พาธของ runtime
- .runtime/launchd/*.plist: ไฟล์งานตามเวลาที่ใช้พาธเครื่องนี้
- outbox/, logs/, capture/: โฟลเดอร์ทำงาน

คำสั่งนี้ไม่ล็อกอิน Google ไม่เขียน Drive ไม่ติดตั้ง launchd และไม่เขียนทับการติดตั้งเดิม ถ้าพาธ/เดือนเปลี่ยน ต้องทบทวนการตั้งค่าใหม่อย่างตั้งใจ

## 7. ตั้ง Google OAuth ของตัวเอง

ตาม [Google Drive Python quickstart](https://developers.google.com/workspace/drive/api/quickstart/python): เปิด Drive API, ตั้ง Google Auth platform/consent และสร้าง OAuth client ชนิด Desktop app ดาวน์โหลด credentials.json ของ client นั้น หากใช้งานแบบ Testing ให้เพิ่มบัญชีที่จะล็อกอินเป็น test user และใช้บัญชีเดียวกันตอนกดอนุญาต

คัดลอก credentials.json ด้วยตัวเองไป `.private/credentials.json` แล้วตั้งสิทธิ์:

```sh
chmod 600 .private/credentials.json
```

อย่าส่ง credentials/token/auth cache ในแชตหรือใส่ ZIP แจก ชุดนี้เตรียม .gitignore ไว้ แต่ผู้ใช้ยังต้องตรวจสิ่งที่จะนำไปแชร์

ทดสอบการเชื่อมต่อในโฟลเดอร์ใหม่ที่แยกจาก Muse:

```sh
.venv/bin/python connect_drive.py --credentials .private/credentials.json --token-file .private/connectivity-token.json --config .private/config.json --test
```

เปิดเบราว์เซอร์ให้ผู้ใช้ล็อกอิน/กด consent เอง ตัวทดสอบสร้างโฟลเดอร์ชื่อ muse-uploader-connectivity-tests-... ที่ราก Drive และส่งไฟล์ .txt ที่ระบุว่าไม่ใช่ Handoff แล้วอ่านกลับตรวจ hash ไม่ส่งไฟล์ตัวอย่างเข้า Muse

จากนั้นอนุญาตการอ่านไฟล์เดิมและส่งไฟล์ของระบบ:

```sh
.venv/bin/python deployment_admin.py login
```

ขั้นนี้ขอ drive.file + drive.readonly เพื่ออ่านไฟล์เดิมที่สร้างโดยแอปอื่นและตรวจว่าเห็น inbox ครบ การขออ่านทั้ง Drive กว้างกว่า drive.file อย่างเดียว ผู้ใช้ต้องพิจารณา consent จริง; สคริปต์ไม่เปลี่ยน sharing permissions และยังไม่เปิดส่ง Handoff

หากเกิด 403 access_denied ให้ตรวจ test user/บัญชี/การตั้ง OAuth ก่อน ไม่แก้ scope เพื่อหลบข้อผิดพลาด หากเป็น External + Testing โดยทั่วไป refresh token ของ scope นี้มีอายุ 7 วันตาม [เอกสาร OAuth ของ Google](https://developers.google.com/identity/protocols/oauth2) จึงต้องทดสอบความต่อเนื่องและตั้งสถานะโครงการอย่างเหมาะสม ไม่ถือว่าการ allow ครั้งเดียวรับประกันรันได้ตลอดไป

## 8. ตรวจปลายทางก่อนเปิดส่งจริง

```sh
.venv/bin/python deployment_admin.py inventory
```

คำสั่งอ่าน inbox และสร้าง `.private/inbox-baseline.json` ให้เจ้าของระบบเปิด Drive ตรวจเทียบรายการและ file IDs อย่างอิสระ ยืนยันว่าเป็นบัญชี/โฟลเดอร์ถูกต้อง เห็นครบ และมี uploader ผู้เขียนเพียงเครื่องเดียว

เมื่อยืนยันแล้ว:

```sh
.venv/bin/python deployment_admin.py enable --reviewed-in-drive --single-writer
```

ถ้า inbox ว่างจริงและตรวจใน Drive แล้ว ให้เพิ่ม `--confirm-empty` ด้วย โปรแกรมจะไม่ถือว่ารายการว่างจาก API เป็นหลักฐานว่าโฟลเดอร์ว่างโดยอัตโนมัติ

ถ้ารายการเปลี่ยนหรืออ่านไฟล์ไม่ครบจะหยุด baseline เดิมไม่ถูกแทนที่เอง ถ้าต้องตรวจชุดใหม่ให้ใช้ `--baseline .private/inbox-baseline-2.json` ทั้งตอน inventory และ enable แล้วตรวจอิสระใหม่

## 9. ส่ง Handoff จริงหนึ่งไฟล์ก่อน

ใช้ Markdown ที่สร้างจากกิจกรรมจริงและผ่าน schema v2 ไม่ใช้ไฟล์ใน examples ใส่ไว้ใน outbox/ ตรวจ dry-run ก่อน:

```sh
.venv/bin/python handoff.py outbox/YOUR_REAL_HANDOFF.md --credentials .private/credentials.json --token-file .private/handoff-token.json --config .private/config.json
```

ถ้าไฟล์/ปลายทางถูกต้องจึงเพิ่ม `--apply` เพื่อส่งจริง แล้วตรวจ verified และให้ Muse ยืนยันการรับตามหน้าที่ของมัน การที่ hash ตรงหมายถึง byte รับส่งถูก ไม่ใช่ Muse ทำ Daily Log สำเร็จแล้ว

Handoff ต้องมี schema_version 2, ID ใหม่, event_date, source/destination/timezone/status/supersedes และ coverage พร้อมหัวข้อ Learning, Projects, Decisions, Open Questions, Next Actions ห้ามมี content_hash ในไฟล์ และไม่อ้าง full history ที่ไม่ได้อ่าน ตัวอย่างรูปแบบอยู่ใน examples/valid-test-handoff.md แต่เป็นข้อมูลทดสอบเท่านั้น

## 10. เชื่อม Session Summary และ AI รวม Handoff

ถ้าแอปมีเครื่องมืออ่านข้อความแชตจริง ให้ทดลองคำสั่งใน CHATGPT_CAPTURE_PROMPT.md กับแชตที่อนุญาตก่อน แล้วตั้งงาน 19:30 JST ผ่านแอป เครื่องมืออาจไม่มีในบางบัญชี/ประเภทแชต การมี Python ไม่ได้เพิ่มสิทธิ์อ่านข้อความเหล่านั้น

ถ้าใช้แบบ manual-assisted ให้สร้าง Session Summary จากแชตต้นทางเอง ระบุ Topics, Progress, Corrected Misunderstandings, Open Questions, Next Actions พร้อมข้อจำกัด coverage ตั้งชื่อ YYYY-MM-DD-topic.md แล้วรวบรวมเข้า session_summaries ก่อน 20:00 ไม่เติมความคืบหน้าจากการคาดเดา

ทดสอบรวมข้อมูลจาก source จริง:

```sh
.venv/bin/python daily_pipeline.py --settings .private/schedule-settings.json
```

แม้ไม่มี --apply คำสั่งนี้ยังเรียก AI และสร้าง Handoff ใน outbox ภายในเครื่อง แต่ไม่อัปโหลด Drive ต้องตรวจไฟล์และ source references จากนั้นจึงรันพร้อม --apply เมื่ออนุญาตส่งจริงแล้ว

ถ้าไม่มี Session Summary ให้รายงาน coverage ที่ขาด ไม่สร้างความคืบหน้าสมมติ AI ในรุ่นนี้เลือกย่อหน้าหลักฐาน Python ดึงข้อความจริงเอง ไม่ใช้คำสรุปของ AI เป็นข้อเท็จจริงใหม่

## 11. ติดตั้ง checkpoint หลังอ่านระบบจริงได้

```sh
.venv/bin/python deployment_admin.py doctor
.venv/bin/python deployment_admin.py checkpoint-test
```

doctor อ่านไฟล์จริงแล้วรายงาน local ผล input_missing ในช่วงเช้าอาจหมายถึงยังไม่มีข้อมูลวันนั้น ไม่ใช่ระบบเสีย รายการ hash mismatch/identity disagreement ต้องตรวจแก้สาเหตุก่อน ไม่ปรับ checkpoint กลบความผิด

checkpoint-test ใช้โฟลเดอร์ connectivity test เดิมที่แยกจาก Muse ทดสอบ create, duplicate, append, backup และ read-back โดยไม่เขียน Production

ตรวจแผนสร้าง ledger โดยไม่เขียน:

```sh
.venv/bin/python deployment_admin.py checkpoint-bootstrap --single-writer
```

เมื่อผลและขอบเขตถูกต้องจึงสร้างจริง:

```sh
.venv/bin/python deployment_admin.py checkpoint-bootstrap --single-writer --apply
```

โปรแกรมสร้าง sync_checkpoints.json ใหม่ บันทึก file ID ใน settings และเก็บ ownership journal ส่วนตัว หากมี ledger เดิมแต่ไม่มี journal จะหยุด ไม่เขียนทับ ดูหัวข้อย้ายเครื่องด้านล่าง

checkpoint มีความหมายเป็น mac_observation ไม่ใช่ execution receipt ของ Muse และ authorization_granted เป็น false เสมอ หากไม่มี Handoff จริงจะบันทึก observation ว่าขาดข้อมูล ไม่สร้าง handoff_id ปลอม content review/การตัดสิน/ขอบเขต required outputs ยัง needs_review

## 12. ตั้ง launchd หลัง manual tests ผ่าน

ตัวติดตั้งปฏิเสธการเปิด uploader ก่อนยืนยันปลายทาง และปฏิเสธ observer ก่อนมี journal ของ ledger ที่ตรวจแล้ว ตั้ง timezone ของ Mac เป็น JST ตามตารางนี้และตรวจอีกครั้ง

```sh
.venv/bin/python manage_launchd.py install --job uploader
.venv/bin/python manage_launchd.py install --job checkpoint
.venv/bin/python manage_launchd.py status --job uploader
.venv/bin/python manage_launchd.py status --job checkpoint
```

ติดตั้งอย่างเดียวไม่รันทันที ตารางคือ uploader 20:00; observer 20:40, 21:10, 21:38, 21:48, 21:55, 22:10 JST ถ้า codex_cli เป็น null งาน 20:00 จะเรียก scheduled_upload.py ส่งเฉพาะ Handoff จริงที่วางไว้ใน outbox ไม่สร้างด้วย AI ตัวตั้งเวลา observer ไม่รับประกันว่า Muse จบงานแล้ว หากไฟล์เปลี่ยนระหว่างอ่านจะหยุดให้ตรวจใหม่

ทดลองเรียก observer หนึ่งรอบ:

```sh
.venv/bin/python manage_launchd.py run --job checkpoint
.venv/bin/python manage_launchd.py status --job checkpoint
```

คำสั่ง run เป็นการรันจริง ตรวจ logs/checkpoint-latest.json และ stdout/stderr ใน logs อย่าใช้ exit 0 หรือ verified แทนคำว่า eligible/healthy เพราะอาจตรวจพบ input_missing/needs_review ได้โดยโปรเซสไม่ล้ม

## 13. เชื่อมงาน Muse ตามสิทธิ์ของเจ้าของระบบ

งานพื้นฐานฝั่ง Muse ที่ระบบอ้างอิงใช้: 20:30 รับ/ตรวจ Handoff; 21:00 retry; 21:30 final retry; 21:40 finalized หรือ incomplete; 21:45 context/Handoff ขากลับ; 22:00 brief; อาทิตย์ 23:15 weekly review

ผู้ติดตั้งต้องให้ Muse อ่านข้อตกลงของตัวเองและยืนยันคำสั่ง/สิทธิ์/confirmation gates ก่อนเปิดงานเหล่านี้ ชุด ZIP ไม่สร้าง scheduled jobs ในบริการ Muse และไม่โอนการอนุมัติของผู้สร้างเดิมให้คนอื่น

หลังมี ledger จริง ให้ใช้ MUSE_LEDGER_ADDENDUM_TEMPLATE.md เติม file IDs ของตัวเอง ขอ Muse สำรองคำสั่งและเพิ่มเฉพาะกฎอ่าน ledger ในงานที่เกี่ยวข้อง รักษาเวลาและกฎเดิม Muse ต้องอ่านไฟล์จริงซ้ำ และไม่เขียน ledger หรือใช้มันอนุมัติ finalize แทนผู้ใช้

ตรวจผลจริงในแชต Muse และข้อความคำสั่งที่เปลี่ยน อย่าถือว่า agent บอกว่าเสร็จเท่ากับทดสอบ scheduled invocation แล้ว

## 14. รันรับรองผล 2–3 รอบจริง

ตรวจตามลำดับ:

- แชต/Session Summary อ้างอิงข้อความจริง ครอบคลุมเท่าที่ประกาศ
- Handoff สร้างและส่งถึง Drive ครั้งเดียว พร้อม hash ตรง
- Muse รับชุดเดียวกัน และ Daily Log มี source references ถูกต้อง
- Mac บันทึก checkpoint จากหลักฐานจริง ไม่มีการอ้างว่า Muse รันครบจากการเห็นไฟล์อย่างเดียว
- ถ้าข้อมูลขาดให้ incomplete/needs_review ตามกฎ ไม่บังคับ finalized หรือ healthy
- retry ไม่สร้าง task/log/revision ซ้ำ และ disagreement ทำให้หยุดจริง
- อ่านผลก่อน–หลังของแต่ละรอบ ไม่สรุปจากชื่อ scheduled task อย่างเดียว

การทดสอบชุดติดตั้งที่ส่งมารวมการแตก ZIP, unit tests และการสร้างค่าตั้งในเครื่องจำลองด้วย IDs สมมติ ไม่ได้ล็อกอินบัญชีใหม่หรือพิสูจน์ unattended ของผู้ติดตั้งใหม่

## 15. หยุดงาน ย้ายเครื่อง และสำรอง

หยุดและถอนเฉพาะงานที่ชุดนี้เป็นเจ้าของ:

```sh
.venv/bin/python manage_launchd.py uninstall --job checkpoint
.venv/bin/python manage_launchd.py uninstall --job uploader
```

คำสั่งเก็บ Drive files, token และ journals ไว้ ไม่ลบประวัติ ถ้ามีงานชื่อเดียวกันจากอีกพาธจะปฏิเสธการเขียนทับ/ถอน ต้องจัดการการติดตั้งเดิมอย่างตั้งใจก่อน

สิ่งที่ต้องสำรองแบบส่วนตัว: deployment.json, .private/, outbox, generation state, uploader state, capture state และ checkpoint-state รวม payload/journal การมี source ZIP อย่างเดียวไม่พอสำหรับกู้ความเป็นเจ้าของ ledger เดิม

ย้ายเครื่องต้องหยุด writer เครื่องเก่าก่อน ใช้บัญชี/Drive IDs เดิมตามที่ตรวจ แล้วโอน private runtime อย่างปลอดภัย สร้าง .venv ใหม่และพาธ launchd ใหม่ อย่าเปิด writer สองเครื่อง generation-state อาจมี output_path แบบ absolute ต้องปรับพาธพร้อมไฟล์จริงอย่างตรวจสอบได้ หากไม่มี journal ให้หยุด reconcile ไม่สร้าง ledger ใหม่ชื่อซ้ำ

ledger จำกัดการใช้งานตามโฟลเดอร์เดือนที่กำหนดและหยุดเมื่อประวัติถึงเงื่อนไข 90 วันเพื่อให้จัด archive ก่อน ไม่มีระบบ archive อัตโนมัติที่พิสูจน์แล้วในชุดนี้

## 16. ไฟล์ไหนทำหน้าที่อะไร

- uploader.py: ตรวจ Handoff และ create-only/read-back/deduplicate
- connect_drive.py: Desktop OAuth และ connectivity test แยก
- handoff.py: ส่ง Handoff จริงแบบ manual
- scheduled_upload.py: ตรวจและส่งคิว outbox แบบไม่เปิดหน้าล็อกอิน
- daily_pipeline.py: อ่าน Session Summaries เรียก Codex CLI เลือกหลักฐาน แล้วสร้าง Handoff
- capture_session.py / capture_batch.py: สร้างและส่งข้อความคัดตรงจาก snapshot แชตที่อ่านจริง
- check_muse.py: ตัวตรวจแบบอ่านอย่างเดียว
- checkpoint_writer.py: writer ledger ของ Mac พร้อม journal/backup/recovery
- deployment_config.py: อ่านขอบเขต IDs/เดือนของการติดตั้งนี้
- prepare_install.py: สร้าง config และ plist เฉพาะเครื่อง
- deployment_admin.py: login, inventory, enable และทดสอบ/bootstrap checkpoint แบบสั่งชัดเจน
- manage_launchd.py: ติดตั้ง ตรวจ เรียก และถอนงานสองรายการที่ชุดนี้เป็นเจ้าของ
- test_*.py / examples/: tests และข้อมูลเทียมสำหรับ local tests
- deployment.example.json / config.local.example.json: แม่แบบค่าตั้ง
- CHATGPT_CAPTURE_PROMPT.md / MUSE_LEDGER_ADDENDUM_TEMPLATE.md: คำสั่งที่ต้องตั้งในแอปและ Muse
- MANIFEST.sha256 / PACKAGE-VERIFICATION.json: ตรวจความครบของชุดไฟล์และขอบเขตผลทดสอบ

ไม่รวม .venv, credentials, tokens, private journals, snapshots แชตจริง หรือไฟล์ Production ของผู้สร้างเดิม ผู้ติดตั้งต้องสร้าง/ย้ายข้อมูลส่วนตัวของตนตามขั้นตอน ไม่คัดการอนุมัติหรือ exception ของคนอื่นมาใช้
