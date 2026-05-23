#!/bin/bash
# Sunucuda çalıştır: bash apply_agy_migration.sh
# Gemini CLI → Antigravity CLI (agy) geçişi — terminal_orchester.py

SERVER="root@207.180.204.66"
REMOTE_FILE="/root/2026-orchester/terminal_orchester.py"

echo "=== AGY Migration: Gemini CLI → Antigravity CLI ==="

# 1. Backup
sshpass -p '7OOxI7GNmXZISU0Hm0slpoKZ25Tt' ssh -o StrictHostKeyChecking=no $SERVER \
  "cp $REMOTE_FILE ${REMOTE_FILE}.bak-gemini && echo 'Backup OK'"

# 2. agy kurulu mu?
sshpass -p '7OOxI7GNmXZISU0Hm0slpoKZ25Tt' ssh -o StrictHostKeyChecking=no $SERVER \
  "which agy && agy --version 2>/dev/null || echo 'UYARI: agy PATH te yok — kurmak gerekiyor'"

# 3. ask_gemini → ask_agy değişikliği
sshpass -p '7OOxI7GNmXZISU0Hm0slpoKZ25Tt' ssh -o StrictHostKeyChecking=no $SERVER "
python3 << 'PYEOF'
from pathlib import Path

path = Path('/root/2026-orchester/terminal_orchester.py')
code = path.read_text()

# ask_gemini fonksiyonunu ask_agy ile değiştir
old_func = '''async def ask_gemini(prompt: str) -> str:
    \"\"\"Google Gemini CLI — subscription / free tier, pipe'da calısır.\"\"\"
    return await run_cli(\"Gemini\", [
        \"gemini\", \"--prompt\", prompt, \"--yolo\",
    ], timeout=180)'''

new_func = '''async def ask_agy(prompt: str) -> str:
    \"\"\"Antigravity CLI (agy) — subscription based, Gemini yerini alır.\"\"\"
    return await run_cli(\"AGY\", [
        \"agy\", \"-i\", prompt,
    ], timeout=180)'''

code = code.replace(old_func, new_func)

# Tüm ask_gemini çağrılarını ask_agy yap
code = code.replace('ask_gemini(', 'ask_agy(')

# gemini dict key ve label'larını güncelle
code = code.replace('\"gemini\": gemini_out', '\"agy\": agy_out')
code = code.replace('\"gemini_draft\": gemini_draft', '\"agy_draft\": agy_draft')
code = code.replace('\"gemini_final\": gemini_final', '\"agy_final\": agy_final')
code = code.replace('gemini_out, gemini_out = await asyncio.gather(', 'agy_out, agy_out = await asyncio.gather(')

# Değişken isimlerini güncelle
code = code.replace('gemini_out,\n', 'agy_out,\n')
code = code.replace(', gemini_out =', ', agy_out =')
code = code.replace('gemini_out = await ask_agy(', 'agy_out = await ask_agy(')
code = code.replace('f\"    Gemini (', 'f\"    AGY (')
code = code.replace('\"gemini_draft\"', '\"agy_draft\"')
code = code.replace('\"gemini_final\"', '\"agy_final\"')
code = code.replace('gemini_draft = await ask_agy(', 'agy_draft = await ask_agy(')
code = code.replace('gemini_final = await ask_agy(', 'agy_final = await ask_agy(')
code = code.replace('gemini_crit', 'agy_crit')
code = code.replace('\"gemini_critique\"', '\"agy_critique\"')

# Yorum satırını güncelle
code = code.replace('Claude + OpenCode + Gemini', 'Claude + OpenCode + AGY')
code = code.replace('Ajanlar: Claude (Anthropic) + OpenCode (DeepSeek) + Gemini (Google)',
                    'Ajanlar: Claude (Anthropic) + OpenCode (DeepSeek) + AGY (Antigravity)')
code = code.replace('Gemini CLI       → Google subscription / free tier',
                    'Antigravity CLI  → AGY subscription / free tier')

path.write_text(code)
print('terminal_orchester.py guncellendi')
PYEOF
"

# 4. Test: agy -i ile basit sorgu
echo "=== Test: agy -i ile basit sorgu ==="
sshpass -p '7OOxI7GNmXZISU0Hm0slpoKZ25Tt' ssh -o StrictHostKeyChecking=no $SERVER \
  "timeout 30 agy -i 'Sadece OK yaz' 2>&1 | head -5 || echo 'TEST BASARISIZ'"

# 5. Servis yeniden başlat
echo "=== Servis yeniden başlatılıyor ==="
sshpass -p '7OOxI7GNmXZISU0Hm0slpoKZ25Tt' ssh -o StrictHostKeyChecking=no $SERVER \
  "systemctl restart orchester.service && sleep 2 && systemctl status orchester.service | head -5"

echo "=== Tamamlandi ==="
echo "Full test icin: hermes -z 'AGY testi: merhaba de'"
