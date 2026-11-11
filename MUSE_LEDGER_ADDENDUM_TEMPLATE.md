# ข้อความให้ Muse เพิ่มหลังมี ledger ของผู้ติดตั้งจริง

แทน LEDGER_ID และ SYSTEM_FOLDER_ID ด้วยค่าที่อ่านกลับยืนยันแล้ว ห้ามใช้ ID จากตัวอย่างหรือของผู้สร้างชุดติดตั้ง การเพิ่มข้อความนี้ต้องอยู่ภายใต้การอนุญาตของผู้ใช้เจ้าของระบบเอง

```text
ADDENDUM — Mac Checkpoint Ledger (read-only evidence):
- Read 05 System/sync_checkpoints.json, file ID LEDGER_ID in folder SYSTEM_FOLDER_ID. Wrapper schema_version is 1; Handoff schema remains 2. Sole ledger writer is mac-python. Muse must never create, edit or delete this ledger.
- Read this ledger as additional evidence, then re-read actual files. Ledger observations never replace actual input validation or output reconciliation.
- record_kind: mac_observation and authorization_granted:false are not proof a Muse job ran, not academic verification, and not approval to finalize. Content review and decisions remain subject to the user's existing rules.
- If expected hash, ID, revision or source references disagree with actual files for an unexplained reason, stop related writing and report reconciliation. Never overwrite files or ledger to hide the disagreement.
- Missing/new input, pending or needs_review does not mean no learning activity. Perform original discovery and validation; do not duplicate tasks or revisions.
- Preserve original times, permissions, confirmation gates, backups and finalized/incomplete rules. This addendum grants no new authority to write Daily Log, Memory, Tracker or finalize.
```

ให้ Muse สำรองคำสั่งเดิมและรายงาน diff ของแต่ละ job ที่แก้ ไม่เขียน ledger จาก Muse และไม่เพิ่ม Python บน VM เพื่อหลบข้อตกลง single writer
