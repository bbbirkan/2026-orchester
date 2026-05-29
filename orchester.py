#!/usr/bin/env python3
"""
2026-Orchester — Claude CLI Tabanlı Multi-Agent Debate
API key gerektirmez. Pro üyelik + `claude -p` kullanır.

Kullanım:
  python orchester.py "Sorum nedir?"
  python orchester.py --rounds 1 "Sorum nedir?"
"""

import asyncio, sys, os, json
from datetime import datetime
from pathlib import Path

# Her ajan aynı Claude modelini kullanır ama farklı perspektiften düşünür
AGENTS = [
    {
        "id": "analyst",
        "name": "Analist",
        "system": (
            "Sen analitik ve bütüncül bir düşünürsün. "
            "Güçlü yanların: derin analiz, etik boyutlar, uzun vadeli sonuçlar, sistematik yaklaşım. "
            "Yanıtını Türkçe ver. Max 300 kelime."
        ),
    },
    {
        "id": "critic",
        "name": "Eleştirmen",
        "system": (
            "Sen eleştirel ve sorgulayıcı bir analistsin. "
            "Güçlü yanların: varsayımları sorgulamak, zayıf noktaları bulmak, alternatif bakış açıları sunmak. "
            "Yanıtını Türkçe ver. Max 300 kelime."
        ),
    },
    {
        "id": "pragmatist",
        "name": "Pragmatist",
        "system": (
            "Sen pratik ve çözüm odaklı bir düşünürsün. "
            "Güçlü yanların: somut adımlar, hızlı uygulama, maliyet-etkin ve ölçülebilir öneriler. "
            "Yanıtını Türkçe ver. Max 300 kelime."
        ),
    },
]

JUDGE_SYSTEM = (
    "Sen tarafsız bir hakemsin. Üç farklı perspektiften gelen tartışmayı okudun. "
    "Görevin: en güçlü argümanları birleştirerek, zayıf noktaları ayıklayarak "
    "KAPSAMLI ve EYLEME GEÇİLEBİLİR bir final yanıtı üret. "
    "Yanıtını Türkçe ver. Max 400 kelime."
)


async def run_claude(user_prompt: str, system_extra: str = None) -> str:
    """claude -p ile headless Claude çalıştır. Pro üyelik kullanır, API key gerektirmez."""
    cmd = [
        "claude", "-p",
        "--dangerously-skip-permissions",
        "--output-format", "text",
    ]
    if system_extra:
        cmd += ["--append-system-prompt", system_extra]
    cmd.append(user_prompt)

    env = {**os.environ, "CLAUDE_CODE_BUBBLEWRAP": "1"}
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd="/root",
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("claude -p zaman aşımına uğradı (120s)")

    if proc.returncode != 0:
        err = stderr.decode()[:300]
        raise RuntimeError(f"claude -p hata kodu {proc.returncode}: {err}")

    return stdout.decode().strip()


async def round_one(task: str) -> dict[str, str]:
    """Her ajan bağımsız cevap verir — paralel."""
    async def ask(agent: dict) -> tuple[str, str]:
        prompt = f"Şu soruya / göreve bağımsız olarak cevap ver:\n\n{task}"
        response = await run_claude(prompt, agent["system"])
        return agent["id"], response

    results = await asyncio.gather(*[ask(a) for a in AGENTS])
    return dict(results)


async def round_two(task: str, r1: dict[str, str]) -> dict[str, str]:
    """Her ajan diğerlerini görüp revize eder — paralel."""
    others_block = "\n\n".join(
        f"**{a['name']}:** {r1[a['id']]}" for a in AGENTS
    )

    async def ask(agent: dict) -> tuple[str, str]:
        prompt = (
            f"Soru/Görev: {task}\n\n"
            f"Diğer ajanların ilk cevapları:\n{others_block}\n\n"
            "Şimdi kendi görüşünü savun veya fikir değiştir — ama gerekçeni açıkla. "
            "Tekrar etme, sadece farklılığını ortaya koy."
        )
        response = await run_claude(prompt, agent["system"])
        return agent["id"], response

    results = await asyncio.gather(*[ask(a) for a in AGENTS])
    return dict(results)


async def synthesize(task: str, r1: dict, r2: dict) -> str:
    """Hakem 2 turdaki tartışmayı sentezler."""
    debate_text = ""
    for a in AGENTS:
        debate_text += f"\n### {a['name']}\n"
        debate_text += f"**Tur 1:** {r1[a['id']]}\n\n"
        if r2 is not r1:
            debate_text += f"**Tur 2:** {r2[a['id']]}\n"

    prompt = (
        f"Soru/Görev: {task}\n\n"
        f"Tartışma:\n{debate_text}\n\n"
        "Final sentez:"
    )
    return await run_claude(prompt, JUDGE_SYSTEM)


def save_debate(task: str, r1: dict, r2: dict, synthesis: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    debates_dir = Path(__file__).parent / "debates"
    debates_dir.mkdir(exist_ok=True)
    out = debates_dir / f"{ts}.md"

    lines = [
        f"# Orchester Tartışması — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"\n**Soru:** {task}\n",
        "---\n",
        "## Tur 1 — Bağımsız Cevaplar\n",
    ]
    for a in AGENTS:
        lines += [f"### {a['name']}\n", r1[a["id"]], "\n"]

    if r2 is not r1:
        lines += ["\n---\n", "## Tur 2 — Karşılıklı Revizyon\n"]
        for a in AGENTS:
            lines += [f"### {a['name']}\n", r2[a["id"]], "\n"]

    lines += ["\n---\n", "## Final Sentezi (Hakem)\n", synthesis, "\n"]
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


async def debate(task: str, rounds: int = 2) -> str:
    print(f"\n[Orchester] {len(AGENTS)} ajan, {rounds} tur — claude -p (Pro üyelik)")

    print("  Tur 1: Bağımsız cevaplar (paralel)...")
    r1 = await round_one(task)
    for a in AGENTS:
        print(f"    {a['name']}: {len(r1[a['id']].split())} kelime")

    r2 = r1
    if rounds >= 2:
        print("  Tur 2: Karşılıklı revizyon (paralel)...")
        r2 = await round_two(task, r1)
        for a in AGENTS:
            print(f"    {a['name']}: {len(r2[a['id']].split())} kelime")

    print("  Hakem sentezi yapıyor...")
    synthesis = await synthesize(task, r1, r2)
    print(f"    Sentez: {len(synthesis.split())} kelime")

    out = save_debate(task, r1, r2, synthesis)
    print(f"  Kaydedildi: {out}")
    return synthesis


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Claude CLI tabanlı multi-agent debate")
    parser.add_argument("task", nargs="+", help="Tartışılacak soru veya görev")
    parser.add_argument("--rounds", type=int, default=2, choices=[1, 2])
    args = parser.parse_args()

    task = " ".join(args.task)
    result = asyncio.run(debate(task, args.rounds))

    print("\n" + "=" * 60)
    print("FINAL SENTEZ:")
    print("=" * 60)
    print(result)
