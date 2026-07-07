#!/bin/zsh
# Dienos bridge'ų refresh: Reddit + X.com + WhatsApp -> data/*.json -> vienas commit+push.
# Leidžiamas launchd 09:15 Mon-Fri (com.daugpinigu.bridges-refresh), prieš
# 10:00 briefing trigerį, kad GH Actions pipeline'as rastų šviežius failus.
# Vieno bridge'o klaida NEnužudo kitų - kiekvienas rašo savo JSON su
# generated_at, o main.py loader'iai patys atmeta stale failus.

ROOT="/Users/radek/Desktop/antigravity/projects/daily-briefing"
PY="$ROOT/venv/bin/python"
STAMP="[bridges $(date '+%Y-%m-%d %H:%M')]"
cd "$ROOT" || exit 1

echo "$STAMP start"
"$PY" scripts/reddit_refresh.py 2>&1 | grep -v NotOpenSSL | grep -v warnings.warn || echo "$STAMP reddit FAILED"
"$PY" scripts/x_refresh.py 2>&1 | grep -v NotOpenSSL | grep -v warnings.warn || echo "$STAMP x FAILED"
"$PY" scripts/wa_refresh.py 2>&1 | grep -v NotOpenSSL | grep -v warnings.warn || echo "$STAMP whatsapp FAILED"

git add data/reddit_posts.json data/x_posts.json data/whatsapp_channel.json 2>/dev/null
if git diff --cached --quiet; then
    echo "$STAMP no changes to commit"
    exit 0
fi
git commit -m "Bridges refresh $(date '+%Y-%m-%d %H:%M') [skip ci]" \
    && git pull --rebase origin main \
    && git push origin main \
    && echo "$STAMP pushed" \
    || echo "$STAMP git push FAILED"
