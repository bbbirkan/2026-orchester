#!/usr/bin/env python3
"""
Terminal Orchester v0.2
3 CLI birbirine bağlı — API key yok, sadece subscription.

  Claude Code CLI  → Anthropic Pro subscription
  OpenCode CLI     → OpenCode Zen subscription (DeepSeek v4 Pro)
  Antigravity CLI  → AGY subscription / free tier

Pipeline (varsayılan: smart):
  Görev → Claude sınıflandırır → basit/orta/zor
  basit  : Claude tek başına (~5sn)
  orta   : Claude + OpenCode paralel, Claude sentezler (~30sn)
  zor    : 3 CLI konsey, max 3 tur (~90sn+)

Kullanım:
  python3 terminal_orchester.py "Sorum veya görevim"
  python3 terminal_orchester.py --mode smart "Görev"
  python3 terminal_orchester.py --mode chain "Görev"
  python3 terminal_orchester.py --mode sequential "Görev"
"""

import asyncio, os, re, shlex, argparse, time
from datetime import datetime
from pathlib import Path

ENV = {**os.environ, "CLAUDE_CODE_BUBBLEWRAP": "1"}
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m|\r")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text).strip()


# ─── CLI çağrı katmanı ──────────────────────────────────────────────────────

async def run_cli(name: str, cmd: list[str], timeout: int = 120) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=ENV,
        cwd="/root",
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return f"[{name}: zaman asimi {timeout}s]"
    if proc.returncode != 0:
        err = strip_ansi(stderr.decode())[:200]
        return f"[{name} hata: {err}]"
    return strip_ansi(stdout.decode())


async def ask_claude(prompt: str) -> str:
    """Anthropic Pro subscription — pipe'da calısır."""
    return await run_cli("Claude", [
        "claude", "-p",
        "--dangerously-skip-permissions",
        "--output-format", "text",
        prompt,
    ], timeout=120)


async def ask_opencode(prompt: str) -> str:
    """OpenCode Zen subscription (DeepSeek v4 Pro) — TTY gerektirir, script ile cozuldu."""
    cmd_str = f"opencode run --dangerously-skip-permissions {shlex.quote(prompt)}"
    raw = await run_cli("OpenCode", [
        "script", "-q", "-c", cmd_str, "/dev/null",
    ], timeout=180)
    lines = [l.strip() for l in raw.splitlines()
             if l.strip() and not l.strip().startswith(">")]
    return "\n".join(lines)


async def ask_agy(prompt: str) -> str:
    """Antigravity CLI — auth gerektiriyor, yoksa hızlı fail."""
    result = await run_cli("AGY", [
        "/root/.local/bin/agy", "-p", prompt,
        "--dangerously-skip-permissions",
    ], timeout=60)
    return result


def _agy_failed(text: str) -> bool:
    return text.startswith("[AGY")


# ─── Akıllı yönlendirme ────────────────────────────────────────────────────

async def classify(task: str) -> str:
    result = await ask_claude(
        "Bu soruyu sınıflandır. Sadece tek kelime yaz: basit, orta veya zor.\n"
        "basit: selamlama, genel sohbet, tek adımlı basit soru\n"
        "orta: teknik soru, araştırma, analiz, karşılaştırma\n"
        "zor: karmaşık karar, mimari tasarım, çok boyutlu problem\n"
        f"Soru: {task}"
    )
    word = result.strip().lower().split()[0] if result.strip() else "orta"
    return word if word in ("basit", "orta", "zor") else "orta"


async def _konsey(task: str) -> dict:
    """3 CLI konsey — max 3 tur, Claude hakem."""
    claude_out = opencode_out = agy_out = ""
    last_synthesis = ""

    for tur in range(1, 4):
        print(f"  Konsey Tur {tur}/3...")
        if tur == 1:
            c_prompt = f"Bu sorunu teknik açıdan analiz et (max 150 kelime, Türkçe):\n{task}"
            o_prompt = f"Bu sorunu implementasyon/kod açısından değerlendir (max 150 kelime, Türkçe):\n{task}"
            g_prompt = f"Bu sorunu geniş perspektif ve araştırma açısından değerlendir (max 150 kelime, Türkçe):\n{task}"
        else:
            ortak = (
                f"Soru: {task}\n\nÖnceki turda uzlaşma sağlanamadı:\n{last_synthesis}\n\n"
                "Çözüme ulaşmak için senin kritik katkın nedir? (max 100 kelime, Türkçe)"
            )
            c_prompt = o_prompt = g_prompt = ortak

        claude_out, opencode_out, agy_out = await asyncio.gather(
            ask_claude(c_prompt),
            ask_opencode(o_prompt),
            ask_agy(g_prompt),
        )
        if _agy_failed(agy_out):
            agy_out = f"[AGY erişilemedi, Claude+OpenCode analizi yeterli]"
        print(f"    CLI'lar yanıtladı ✓")

        evaluation = await ask_claude(
            f"Soru: {task}\n\n"
            f"Claude analizi:\n{claude_out}\n\n"
            f"OpenCode analizi:\n{opencode_out}\n\n"
            f"AGY analizi:\n{agy_out}\n\n"
            "Bu perspektiflerden tutarlı bir sonuca ulaşabilir misin? "
            "İlk kelime olarak 'EVET' veya 'HAYIR' yaz, sonra yanıtı ver (max 300 kelime, Türkçe):"
        )
        last_synthesis = evaluation

        if evaluation.strip().upper().startswith("EVET"):
            print(f"    Tur {tur}'de uzlaşma sağlandı ✓")
            return {
                "mode": f"smart:zor:tur{tur}",
                "task": task,
                "agents": {"claude": claude_out, "opencode": opencode_out, "agy": agy_out},
                "synthesis": evaluation,
            }

    # 3 turdan sonra çözülemediyse
    return {
        "mode": "smart:zor:cozumsuz",
        "task": task,
        "agents": {"claude": claude_out, "opencode": opencode_out, "agy": agy_out},
        "synthesis": f"3 tur denendi, kesin sonuca ulaşılamadı. En iyi yaklaşım:\n{last_synthesis}",
    }


async def mode_smart(task: str) -> dict:
    """
    SMART — Claude sınıflandırır, seviyeye göre yönlendirir
    basit  → Claude tek
    orta   → Claude + OpenCode paralel, Claude sentezler
    zor    → 3 CLI konsey, max 3 tur
    """
    print("  Mod: SMART")
    print("  Sınıflandırma...")
    level = await classify(task)
    print(f"    Seviye: {level.upper()}")

    if level == "basit":
        print("  → Claude tek başına")
        answer = await ask_claude(f"{task}")
        print(f"    Claude ({len(answer.split())} kelime) ✓")
        return {"mode": "smart:basit", "task": task, "agents": {"claude": answer}, "synthesis": answer}

    elif level == "orta":
        print("  → Claude + OpenCode paralel, Claude sentezliyor...")
        claude_out, opencode_out = await asyncio.gather(
            ask_claude(f"Bu soruya kendi perspektifinden cevap ver (max 150 kelime, Türkçe):\n{task}"),
            ask_opencode(f"Bu soruya teknik perspektiften cevap ver (max 150 kelime, Türkçe):\n{task}"),
        )
        print(f"    Claude ({len(claude_out.split())}) + OpenCode ({len(opencode_out.split())}) ✓")
        synthesis = await ask_claude(
            f"Soru: {task}\n\nKendi analizin:\n{claude_out}\n\n"
            f"OpenCode analizi:\n{opencode_out}\n\n"
            "Bu iki perspektifi birleştirerek en iyi yanıtı üret (max 200 kelime, Türkçe):"
        )
        print(f"    Sentez ({len(synthesis.split())} kelime) ✓")
        return {
            "mode": "smart:orta",
            "task": task,
            "agents": {"claude": claude_out, "opencode": opencode_out},
            "synthesis": synthesis,
        }

    else:  # zor
        print("  → Konsey (Claude + OpenCode, max 3 tur)...")
        return await _konsey(task)


# ─── Orkestrasyon modları ───────────────────────────────────────────────────

async def mode_parallel(task: str) -> dict:
    """
    PARALLEL — Claude + OpenCode esanli, AGY sentezi
    [Claude]   --+
                 +--> AGY --> Final
    [OpenCode] --+
    """
    print("  Mod: PARALLEL")
    print("  Adim 1/2: Claude + OpenCode ayni anda calisiyor...")

    claude_out, opencode_out = await asyncio.gather(
        ask_claude(f"Bu gorevi analiz et, gorusunu net ve oz anlat (max 200 kelime, Turkce):\n{task}"),
        ask_opencode(f"Bu goreve teknik ve pratik acilardan bak, somut oneriler sun (max 200 kelime, Turkce):\n{task}"),
    )
    print(f"    Claude ({len(claude_out.split())} kelime) ✓")
    print(f"    OpenCode ({len(opencode_out.split())} kelime) ✓")

    print("  Adim 2/2: AGY sentezi...")
    agy_out = await ask_agy(
        f"Gorev: {task}\n\n"
        f"=== Claude Analizi ===\n{claude_out}\n\n"
        f"=== OpenCode Analizi ===\n{opencode_out}\n\n"
        "Bu iki perspektifi birlestirerek KAPSAMLI ve EYLEME GECILEBILIR "
        "bir final yaniti uret (max 300 kelime, Turkce):"
    )

    if _agy_failed(agy_out):
        print(f"    AGY başarısız, Claude sentezliyor...")
        agy_out = await ask_claude(
            f"Gorev: {task}\n\n"
            f"=== Claude Analizi ===\n{claude_out}\n\n"
            f"=== OpenCode Analizi ===\n{opencode_out}\n\n"
            "Bu iki perspektifi birlestirerek en iyi yaniti uret (max 300 kelime, Turkce):"
        )
    print(f"    Sentez ({len(agy_out.split())} kelime) ✓")

    return {
        "mode": "parallel",
        "task": task,
        "agents": {"claude": claude_out, "opencode": opencode_out, "agy": agy_out},
        "synthesis": agy_out,
    }


async def mode_chain(task: str) -> dict:
    """
    CHAIN — Claude → OpenCode → AGY sirayla, her biri oncekini gorur
    [Claude] → [OpenCode] → [AGY] → Final
    """
    print("  Mod: CHAIN")
    print("  Adim 1/3: Claude analiz yapiyor...")
    claude_out = await ask_claude(
        f"Bu gorevi analiz et, gorusunu net anlat (max 200 kelime, Turkce):\n{task}"
    )
    print(f"    Claude ({len(claude_out.split())} kelime) ✓")

    print("  Adim 2/3: OpenCode Claude'u gordu, ekliyor...")
    opencode_out = await ask_opencode(
        f"Gorev: {task}\n\nClaude bunu soyledi:\n{claude_out}\n\n"
        "Claude'a katil veya itiraz et, teknik boyutlari ekle (max 200 kelime, Turkce):"
    )
    print(f"    OpenCode ({len(opencode_out.split())} kelime) ✓")

    print("  Adim 3/3: AGY ikisini gordu, final karar veriyor...")
    agy_out = await ask_agy(
        f"Gorev: {task}\n\n"
        f"=== Claude ===\n{claude_out}\n\n"
        f"=== OpenCode ===\n{opencode_out}\n\n"
        "Bu tartismadan kesin final karara var (max 300 kelime, Turkce):"
    )
    print(f"    AGY ({len(agy_out.split())} kelime) ✓")

    return {
        "mode": "chain",
        "task": task,
        "agents": {"claude": claude_out, "opencode": opencode_out, "agy": agy_out},
        "synthesis": agy_out,
    }


async def mode_sequential(task: str) -> dict:
    """
    SEQUENTIAL — AGY taslak, Claude + OpenCode elestiri (paralel), AGY revize
    [AGY draft] → [Claude + OpenCode elestiri] → [AGY final]
    """
    print("  Mod: SEQUENTIAL")
    print("  Adim 1/3: AGY taslak olusturuyor...")
    agy_draft = await ask_agy(
        f"Bu goreve dair taslak analiz uret (max 200 kelime, Turkce):\n{task}"
    )
    print(f"    AGY taslak ({len(agy_draft.split())} kelime) ✓")

    print("  Adim 2/3: Claude + OpenCode elestiri yapiyor (paralel)...")
    critique_prompt = (
        f"Gorev: {task}\n\nAGY taslagi:\n{agy_draft}\n\n"
        "Bu taslagi elestir, eksiklerini bul (max 150 kelime, Turkce):"
    )
    claude_crit, opencode_crit = await asyncio.gather(
        ask_claude(critique_prompt),
        ask_opencode(critique_prompt),
    )
    print(f"    Claude elestiri ({len(claude_crit.split())} kelime) ✓")
    print(f"    OpenCode elestiri ({len(opencode_crit.split())} kelime) ✓")

    print("  Adim 3/3: AGY elestirilerle revize ediyor...")
    agy_final = await ask_agy(
        f"Gorev: {task}\n\nSenin taslagin:\n{agy_draft}\n\n"
        f"Claude elestirisi:\n{claude_crit}\n\nOpenCode elestirisi:\n{opencode_crit}\n\n"
        "Elestiriler isiginda revize et, en iyi final yaniti uret (max 300 kelime, Turkce):"
    )
    print(f"    AGY final ({len(agy_final.split())} kelime) ✓")

    return {
        "mode": "sequential",
        "task": task,
        "agents": {
            "agy_draft": agy_draft,
            "claude_critique": claude_crit,
            "opencode_critique": opencode_crit,
            "agy_final": agy_final,
        },
        "synthesis": agy_final,
    }


# ─── Kaydet ve calistir ─────────────────────────────────────────────────────

WIKI_PATH = Path(os.environ.get("WIKI_PATH", "/root/wiki"))
GRAPHIFY_BIN = os.environ.get("GRAPHIFY_BIN", str(Path.home() / ".local/bin/graphify"))


def save_result(result: dict) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 1. debates/ dizinine kaydet (mevcut davranış)
    out_dir = Path(__file__).parent / "debates"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{ts}_{result['mode']}.md"

    lines = [
        f"# Terminal Orchester — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"\n**Mod:** {result['mode'].upper()}  **Ajanlar:** Claude + OpenCode + AGY",
        f"\n**Gorev:** {result['task']}\n", "---\n",
    ]
    for name, content in result["agents"].items():
        lines += [f"## {name.replace('_', ' ').title()}\n", content, "\n"]
    lines += ["\n---\n", "## Final Sentezi\n", result["synthesis"], "\n"]
    content_str = "\n".join(lines)
    out.write_text(content_str, encoding="utf-8")

    # 2. Wiki raw/debates/ dizinine kopyala (Graphify için)
    wiki_debates = WIKI_PATH / "raw" / "debates"
    wiki_debates.mkdir(parents=True, exist_ok=True)
    (wiki_debates / out.name).write_text(content_str, encoding="utf-8")

    return out


def update_graphify():
    """Graphify ile wiki knowledge graph'ını güncelle."""
    import subprocess
    if not Path(GRAPHIFY_BIN).exists():
        print(f"  [Graphify] binary bulunamadi: {GRAPHIFY_BIN}")
        return
    try:
        result = subprocess.run(
            [GRAPHIFY_BIN, "update", str(WIKI_PATH)],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            print(f"  [Graphify] wiki guncellendi: {WIKI_PATH}")
        else:
            print(f"  [Graphify] hata: {result.stderr[:100]}")
    except Exception as e:
        print(f"  [Graphify] calistirilamadi: {e}")


MODES = {
    "smart": mode_smart,
    "parallel": mode_parallel,
    "chain": mode_chain,
    "sequential": mode_sequential,
}


_MODE_LABELS = {
    "basit": "Simple",
    "orta": "Medium",
    "zor": "Complex",
    "cozumsuz": "Complex",
}


def _build_footer(result: dict, elapsed: int) -> str:
    """Response footer with mode / models / duration / token estimate."""
    raw_label = result.get("mode", "").split(":")[1] if ":" in result.get("mode", "") else result.get("mode", "")
    mode_label = _MODE_LABELS.get(raw_label, raw_label.capitalize())

    agents = result.get("agents", {})
    models = []
    if any(k in agents for k in ("claude", "claude_critique")):
        models.append("Claude Sonnet 4.6")
    if any(k in agents for k in ("opencode", "opencode_critique")):
        models.append("OpenCode")
    if "agy" in agents and not _agy_failed(agents.get("agy", "[AGY")):
        models.append("AGY")
    if "agy_draft" in agents or "agy_final" in agents:
        models.append("AGY")

    all_text = " ".join(str(v) for v in agents.values()) + " " + result.get("synthesis", "")
    token_est = int(len(all_text.split()) * 1.3 / 100) * 100 or 100

    model_str = " · ".join(models)
    return f"\n\n---\n{mode_label} · {model_str} · {elapsed}s · ~{token_est:,} tokens"


async def orchestrate(task: str, mode: str = "parallel", wiki: bool = True) -> dict:
    print(f"\n[Terminal Orchester v0.2]")
    print(f"Mod: {mode.upper()} | Gorev: {task[:70]}...")
    t0 = time.time()
    result = await MODES.get(mode, mode_parallel)(task)
    elapsed = int(time.time() - t0)
    result["elapsed"] = elapsed
    result["footer"] = _build_footer(result, elapsed)
    out = save_result(result)
    print(f"\n  Kaydedildi: {out} ({elapsed}sn)")
    if wiki:
        update_graphify()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="3 CLI terminal orkestrasyon — API key yok")
    parser.add_argument("task", nargs="+", help="Gorev veya soru")
    parser.add_argument("--mode", choices=list(MODES.keys()), default="parallel")
    args = parser.parse_args()

    result = asyncio.run(orchestrate(" ".join(args.task), args.mode))
    print("\n" + "=" * 60)
    print("FINAL:")
    print("=" * 60)
    print(result["synthesis"])
