#!/usr/bin/env python3
"""
YouTube Transcript & Analysis Tool for Jarvis — Silent Empire AI
Uses OpenRouter (Gemini 2.0 Flash) to extract and analyze YouTube content.
No IP bans, no cookies, no yt-dlp n challenge issues.

Usage:
    # Get transcript + analysis of a single video
    python3 youtube_transcript.py "https://www.youtube.com/watch?v=VIDEO_ID"

    # Research mode — search + analyze multiple videos via youtube_research.py metadata
    python3 youtube_transcript.py --analyze-results /path/to/youtube_research.json

    # Quick competitive intel on a topic
    python3 youtube_transcript.py --topic "asset protection trust divorce" --max 3
"""

import json
import os
import sys
import urllib.request
import urllib.error
import argparse
from datetime import datetime
from pathlib import Path

API_URL = "https://openrouter.ai/api/v1/chat/completions"
API_KEY = os.environ.get("OPENROUTER_KEY", "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")

REPORTS_DIR = Path("/srv/silentempire/ai-firm/data/reports/research")

# ── Core transcript + analysis function ──────────────────────────────────────

def analyze_video(url: str, analysis_focus: str = None) -> dict:
    """
    Extract transcript and analyze a YouTube video via Gemini through OpenRouter.
    Returns dict with: url, title, transcript_excerpt, key_points, content_summary,
                       competitive_insights, quotable_moments, content_angles
    """
    focus = analysis_focus or (
        "This is for Silent Empire AI — a trust and asset protection business targeting "
        "high-income men (35-55, $120K+/year) who fear losing assets in divorce, lawsuits, "
        "or to creditors. Extract what's most relevant for competitive intelligence and "
        "content strategy for Silent Vault Trust System."
    )

    prompt = f"""Analyze this YouTube video for competitive intelligence and content strategy.

Video URL: {url}

Instructions:
1. Extract the key transcript content and main points from this video
2. Identify what the speaker is teaching or selling
3. Note specific claims, frameworks, mechanisms, or strategies mentioned
4. Extract any specific statistics, case studies, or proof points used
5. Identify the target audience and pain points being addressed

Business Context: {focus}

Return your analysis in this exact structure:

## Video Title
[title of the video]

## Channel & Context
[channel name, estimated audience, video positioning]

## Core Message
[What is the main argument or teaching of this video in 2-3 sentences]

## Key Points Extracted
[5-10 specific points from the transcript — not summaries, actual content]

## Frameworks or Mechanisms Named
[Any named strategies, systems, or frameworks the speaker uses]

## Specific Claims & Data
[Any statistics, case studies, success stories, or specific claims made]

## Target Audience & Pain Points
[Who they're speaking to and what fears/desires they're addressing]

## Competitive Intelligence for Silent Vault
[What this means for our positioning — where they're weak, what we can do better,
what they're saying that validates our approach, what angles they're missing]

## Content Angles We Can Own
[3-5 specific content ideas inspired by this video that Silent Vault can execute better]

## Quotable Moments
[2-3 specific things said that reveal market language — exact phrasing the audience uses]

Be specific. If you cannot access the video, say so clearly — do not fabricate content."""

    body = json.dumps({
        "model": "google/gemini-2.0-flash-001",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a competitive intelligence analyst for Silent Empire AI. "
                    "You analyze YouTube content to extract competitive insights, market language, "
                    "and content opportunities for Silent Vault Trust System — an asset protection "
                    "service for high-income men. Be specific and analytical, not generic."
                )
            },
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 2048,
        "temperature": 0.2,
    }).encode()

    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://silentempireai.com",
            "X-Title": "Silent Empire YouTube Intelligence",
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            j = json.loads(r.read())
            content = j["choices"][0]["message"]["content"]
            return {
                "url": url,
                "analysis": content,
                "success": True,
                "model": "google/gemini-2.0-flash-001",
                "timestamp": datetime.now().strftime("%Y-%m-%d_%H-%M"),
            }
    except urllib.error.HTTPError as e:
        err = e.read().decode()[:300]
        return {
            "url": url,
            "analysis": f"API error {e.code}: {err}",
            "success": False,
            "error": err,
        }
    except Exception as e:
        return {
            "url": url,
            "analysis": f"Error: {e}",
            "success": False,
            "error": str(e),
        }


# ── Research mode — analyze results from youtube_research.py ─────────────────

def analyze_research_results(json_path: str, max_videos: int = 5) -> list:
    """
    Takes output JSON from youtube_research.py and runs transcript analysis
    on each video URL via OpenRouter.
    """
    try:
        data = json.loads(Path(json_path).read_text())
    except Exception as e:
        print(f"Error reading results file: {e}", file=sys.stderr)
        sys.exit(1)

    results = data.get("results", [])
    query   = data.get("query", "unknown")
    analyses = []

    print(f"[youtube_transcript] Analyzing {min(len(results), max_videos)} videos for: {query!r}")

    for i, r in enumerate(results[:max_videos], 1):
        url = r.get("url", "")
        title = r.get("title", "Unknown")
        if not url:
            continue
        print(f"  [{i}/{min(len(results), max_videos)}] {title[:60]}")
        analysis = analyze_video(url)
        analysis["title"]   = title
        analysis["channel"] = r.get("channel", "")
        analysis["views"]   = r.get("views")
        analyses.append(analysis)

    return analyses


# ── Topic mode — search + analyze in one shot ─────────────────────────────────

def research_topic(topic: str, max_videos: int = 3) -> str:
    """
    Full pipeline: use Perplexity to find relevant YouTube videos,
    then analyze each one via Gemini.
    Returns formatted report string.
    """
    # Step 1: Find videos via youtube_research.py (search only, no transcripts)
    import subprocess
    tools_dir = Path(__file__).parent

    print(f"[youtube_transcript] Searching YouTube for: {topic!r}")
    search_result = subprocess.run(
        [sys.executable, str(tools_dir / "youtube_research.py"),
         topic, "--max-results", str(max_videos), "--json-only"],
        capture_output=True, text=True, timeout=60
    )

    videos = []
    if search_result.returncode == 0:
        try:
            # Find JSON in output
            out = search_result.stdout.strip()
            # youtube_research.py --json-only prints the results JSON
            videos = json.loads(out)
        except Exception:
            pass

    if not videos:
        print("[youtube_transcript] Search failed or returned no results. Trying direct analysis.", flush=True)
        # Fall back to asking Gemini to find and analyze relevant videos
        return analyze_topic_direct(topic)

    # Step 2: Analyze each video
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    slug = topic[:40].lower().replace(" ", "-").replace("'", "")
    save_path = REPORTS_DIR / f"{ts}_youtube-intelligence_{slug}.md"

    report_lines = [
        f"# YouTube Competitive Intelligence — {topic}",
        f"**Date:** {ts}",
        f"**Videos Analyzed:** {len(videos[:max_videos])}",
        "---\n",
    ]

    for i, v in enumerate(videos[:max_videos], 1):
        url   = v.get("url", "")
        title = v.get("title", "Unknown")
        if not url:
            continue

        print(f"  [{i}/{min(len(videos), max_videos)}] Analyzing: {title[:60]}")
        result = analyze_video(url)

        report_lines.append(f"## Video {i}: {title}")
        report_lines.append(f"**Channel:** {v.get('channel','?')} | **Views:** {v.get('views','?')}")
        report_lines.append(f"**URL:** {url}\n")
        report_lines.append(result["analysis"])
        report_lines.append("\n---\n")

    report = "\n".join(report_lines)

    # Save report
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    save_path.write_text(report)
    print(f"[youtube_transcript] Report saved → {save_path}")

    return report


def analyze_topic_direct(topic: str) -> str:
    """
    Direct mode — ask Gemini to find and analyze YouTube content on a topic
    without using youtube_research.py first.
    """
    prompt = f"""Search YouTube for videos about "{topic}" and analyze the top results.

For each of the 3 most relevant videos you find:
1. Provide the video URL
2. Extract the main teaching/message
3. Identify competitive insights for Silent Vault Trust System
4. Extract market language the audience uses
5. Identify content angles Silent Vault can own

Business context: Silent Vault is an irrevocable trust service for high-income men
(35-55, $120K+/year) protecting assets from divorce, lawsuits, and creditors.
Price: $5K-$25K. Faster and cheaper than attorneys (7-10 days vs 6-18 weeks).

Format as a competitive intelligence report with clear sections per video."""

    body = json.dumps({
        "model": "google/gemini-2.0-flash-001",
        "messages": [
            {"role": "system", "content": "You are a competitive intelligence analyst. Find and analyze YouTube content to extract market insights."},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 3000,
        "temperature": 0.2,
    }).encode()

    req = urllib.request.Request(
        API_URL, data=body,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://silentempireai.com",
            "X-Title": "Silent Empire YouTube Intelligence",
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            j = json.loads(r.read())
            return j["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Error: {e}"


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="YouTube transcript and competitive intelligence via OpenRouter"
    )
    parser.add_argument("url", nargs="?", help="YouTube URL to analyze")
    parser.add_argument("--analyze-results", help="Path to youtube_research.py JSON output")
    parser.add_argument("--topic", help="Research a topic end-to-end (search + analyze)")
    parser.add_argument("--max", type=int, default=3, help="Max videos to analyze (default: 3)")
    parser.add_argument("--focus", help="Custom analysis focus/context")
    parser.add_argument("--save", help="Path to save report (optional)")

    args = parser.parse_args()

    ts   = datetime.now().strftime("%Y-%m-%d_%H-%M")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # ── Single URL mode ───────────────────────────────────────────────────────
    if args.url:
        print(f"[youtube_transcript] Analyzing: {args.url}")
        result = analyze_video(args.url, args.focus)

        print("\n" + "="*70)
        print(result["analysis"])
        print("="*70)

        save_path = Path(args.save) if args.save else REPORTS_DIR / f"{ts}_youtube-analysis.md"
        save_path.write_text(
            f"# YouTube Analysis\n**URL:** {args.url}\n**Date:** {ts}\n\n---\n\n{result['analysis']}"
        )
        print(f"\n[youtube_transcript] Saved → {save_path}")
        return

    # ── Analyze existing research results ─────────────────────────────────────
    if args.analyze_results:
        analyses = analyze_research_results(args.analyze_results, args.max)
        report_lines = [f"# YouTube Intelligence Report\n**Date:** {ts}\n\n---\n"]
        for a in analyses:
            report_lines.append(f"## {a.get('title','Video')}")
            report_lines.append(f"**URL:** {a['url']}\n")
            report_lines.append(a["analysis"])
            report_lines.append("\n---\n")

        report = "\n".join(report_lines)
        save_path = Path(args.save) if args.save else REPORTS_DIR / f"{ts}_youtube-intelligence.md"
        save_path.write_text(report)
        print(f"\n[youtube_transcript] Report saved → {save_path}")
        print("\n" + report[:3000])
        return

    # ── Topic research mode ───────────────────────────────────────────────────
    if args.topic:
        report = research_topic(args.topic, args.max)
        print("\n" + "="*70)
        print(report[:4000])
        print("="*70)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
