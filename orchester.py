#!/usr/bin/env python3
"""
2026-Orchester — Multi-Agent Debate System
Claude vs Gemini vs GLM-4.7: 2-round debate + hakem sentezi

Kullanım:
  python orchester.py "Sorum nedir?"
  python orchester.py --rounds 1 "Sorum nedir?"
"""

import asyncio, httpx, json, sys, os
from datetime import datetime
from pathlib import Path

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
OR_BASE = "https://openrouter.ai/api/v1/chat/completions"

AGENTS = [
    {
        "id": "claude",
        "name": "Claude Sonnet",
        "model": "anthropic/claude-sonnet-4-5",
        "role": "Analitik ve bütüncül düşünür. Güçlü yanları: derin analiz, etik boyutlar, bağlam.",
    },
    {
        "id": "gemini",
        "name": "Gemini 2.5 Flash",
        "model": "google/gemini-2.5-flash",
        "role": "Hızlı ve yaratıcı. Güçlü yanları: multimodal bağlantılar, yeni perspektifler, pratik öneriler.",
    },
    {
        "id": "glm",
        "name": "GLM-4.7",
        "model": "z-ai/glm-4.7",
        "role": "Verimli ve odaklı. Güçlü yanları: kesin cevaplar, kısa formül, maliyet-etkin delegasyon.",
    },
]

JUDGE = {
    "name": "Hakem (Claude)",
    "model": "anthropic/claude-sonnet-4-5",
}


async def call_model(model: str, messages: list[dict]) -> str:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "HTTP-Referer": "https://birkan.ai",
        "X-Title": "2026-Orchester",
    }
    payload = {"model": model, "messages": messages, "max_tokens": 1024}
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(OR_BASE, headers=headers, json=payload)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()


async def round_one(task: str) -> dict[str, str]:
    """Her ajan bağımsız cevap verir."""
    system_tmpl = (
        "Sen bir yapay zeka ajansın. Kimliğin: {name}. Rolün: {role}\n"
        "Soruya dürüst ve özgün cevap ver. Kısa ama öz ol (max 300 kelime)."
    )

    async def ask(agent):
        msgs = [
            {"role": "system", "content": system_tmpl.format(**agent)},
            {"role": "user", "content": task},
        ]
        return agent["id"], await call_model(agent["model"], msgs)

    results = await asyncio.gather(*[ask(a) for a in AGENTS])
    return dict(results)


async def round_two(task: str, r1: dict[str, str]) -> dict[str, str]:
    """Her ajan diğerlerini görüp revize eder."""
    others_tmpl = "\n\n".join(
        f"**{a['name']}:** {r1[a['id']]}"
        for a in AGENTS
    )

    system_tmpl = (
        "Sen {name} ajansısın. Rolün: {role}\n"
        "Aşağıda diğer ajanların ilk cevapları var. "
        "Kendi görüşünü savun veya fikir değiştir — ama gerekçeni açıkla. "
        "Tekrar etme, sadece farklılığını ortaya koy (max 250 kelime)."
    )

    async def ask(agent):
        user_msg = (
            f"Soru: {task}\n\n"
            f"Diğer ajanların cevapları:\n{others_tmpl}\n\n"
            "Şimdi sen revize et veya savun:"
        )
        msgs = [
            {"role": "system", "content": system_tmpl.format(**agent)},
            {"role": "user", "content": user_msg},
        ]
        return agent["id"], await call_model(agent["model"], msgs)

    results = await asyncio.gather(*[ask(a) for a in AGENTS])
    return dict(results)


async def synthesize(task: str, r1: dict, r2: dict) -> str:
    """Hakem 2 turdaki tartışmayı sentezler."""
    debate_text = ""
    for a in AGENTS:
        debate_text += f"\n### {a['name']}\n"
        debate_text += f"**Tur 1:** {r1[a['id']]}\n\n"
        debate_text += f"**Tur 2:** {r2[a['id']]}\n"

    msgs = [
        {
            "role": "system",
            "content": (
                "Sen tarafsız bir hakemsin. Üç yapay zekanın 2 turluk tartışmasını okudun. "
                "Görevin: en güçlü argümanları birleştirerek, zayıf noktaları ayıklayarak "
                "KAPSAMLI ve EYLEME GEÇİLEBİLİR bir final yanıtı üret (max 400 kelime)."
            ),
        },
        {
            "role": "user",
            "content": f"Soru: {task}\n\nTartışma:\n{debate_text}\n\nFinal sentez:",
        },
    ]
    return await call_model(JUDGE["model"], msgs)


def save_debate(task: str, r1: dict, r2: dict, synthesis: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(__file__).parent / "debates" / f"{ts}.md"
    lines = [
        f"# Orchester Tartışması — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"\n**Soru:** {task}\n",
        "---\n",
        "## Tur 1 — Bağımsız Cevaplar\n",
    ]
    for a in AGENTS:
        lines += [f"### {a['name']}\n", r1[a["id"]], "\n"]

    lines += ["\n---\n", "## Tur 2 — Karşılıklı Revizyon\n"]
    for a in AGENTS:
        lines += [f"### {a['name']}\n", r2[a["id"]], "\n"]

    lines += ["\n---\n", "## Final Sentezi (Hakem)\n", synthesis, "\n"]
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


async def debate(task: str, rounds: int = 2) -> str:
    print(f"\n🎭 Orchester başlıyor: {len(AGENTS)} ajan, {rounds} tur\n")

    print("⏳ Tur 1: Bağımsız cevaplar...")
    r1 = await round_one(task)
    for a in AGENTS:
        print(f"  ✅ {a['name']}: {len(r1[a['id']].split())} kelime")

    r2 = r1  # default if rounds=1
    if rounds >= 2:
        print("\n⏳ Tur 2: Karşılıklı revizyon...")
        r2 = await round_two(task, r1)
        for a in AGENTS:
            print(f"  ✅ {a['name']}: {len(r2[a['id']].split())} kelime")

    print("\n⏳ Hakem sentezi yapıyor...")
    synthesis = await synthesize(task, r1, r2)
    print(f"  ✅ Sentez: {len(synthesis.split())} kelime")

    out = save_debate(task, r1, r2, synthesis)
    print(f"\n💾 Kaydedildi: {out}")
    return synthesis


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Multi-agent debate")
    parser.add_argument("task", nargs="+", help="Tartışılacak soru veya görev")
    parser.add_argument("--rounds", type=int, default=2, choices=[1, 2])
    args = parser.parse_args()

    task = " ".join(args.task)
    result = asyncio.run(debate(task, args.rounds))

    print("\n" + "=" * 60)
    print("FINAL SENTEZ:")
    print("=" * 60)
    print(result)
