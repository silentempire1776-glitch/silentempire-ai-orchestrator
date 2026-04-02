#!/usr/bin/env python3
"""
YouTube Research Tool — Silent Empire AI
Search YouTube, extract transcripts, analyze content without LLM calls.

CLI usage:
    python3 youtube_research.py "stoic philosophy daily habits" --max-results 5

Importable:
    from youtube_research import search_and_analyze
    results = search_and_analyze("query", max_results=5)
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

# ── third-party ──────────────────────────────────────────────────────────────
try:
    import yt_dlp
except ImportError:
    sys.exit("yt-dlp not installed. Run: pip3 install yt-dlp")

# youtube-transcript-api kept as optional fallback
try:
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import (
        NoTranscriptFound,
        TranscriptsDisabled,
        RequestBlocked,
    )
    _YT_TRANSCRIPT_API_AVAILABLE = True
except ImportError:
    _YT_TRANSCRIPT_API_AVAILABLE = False
    YouTubeTranscriptApi = None
    NoTranscriptFound = TranscriptsDisabled = RequestBlocked = Exception
except Exception:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
        RequestBlocked = Exception
        _YT_TRANSCRIPT_API_AVAILABLE = True
    except Exception:
        _YT_TRANSCRIPT_API_AVAILABLE = False
        YouTubeTranscriptApi = None
        NoTranscriptFound = TranscriptsDisabled = RequestBlocked = Exception

# ── constants ─────────────────────────────────────────────────────────────────
REPORTS_DIR = Path("/srv/silentempire/ai-firm/data/reports/agent")

STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "up", "about", "into", "through", "during",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "could", "should", "may", "might",
    "shall", "can", "need", "dare", "used", "ought", "i", "you", "he", "she",
    "it", "we", "they", "me", "him", "her", "us", "them", "my", "your",
    "his", "its", "our", "their", "this", "that", "these", "those", "what",
    "which", "who", "when", "where", "why", "how", "all", "each", "every",
    "both", "few", "more", "most", "other", "some", "such", "no", "not",
    "only", "same", "so", "than", "too", "very", "just", "because", "as",
    "until", "while", "if", "then", "there", "here", "again", "also",
    "like", "get", "got", "go", "going", "know", "think", "make", "want",
    "one", "two", "three", "s", "t", "re", "ve", "ll", "m", "d",
}


# ── search ────────────────────────────────────────────────────────────────────

def search_youtube(query: str, max_results: int = 5) -> list[dict]:
    """Return list of video metadata dicts via yt-dlp search."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        "playlist_items": f"1-{max_results}",
        "ignoreerrors": True,
    }
    search_url = f"ytsearch{max_results}:{query}"
    videos = []
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(search_url, download=False)
        if not info or "entries" not in info:
            raise RuntimeError(f"yt-dlp returned no results for query: {query!r}")
        for entry in info["entries"]:
            if not entry:
                continue
            vid_id = entry.get("id") or entry.get("url", "").split("v=")[-1]
            videos.append({
                "video_id": vid_id,
                "title": entry.get("title", "Unknown"),
                "url": f"https://www.youtube.com/watch?v={vid_id}",
                "channel": entry.get("uploader") or entry.get("channel", "Unknown"),
                "views": entry.get("view_count"),
                "duration": entry.get("duration"),
            })
    return videos


# ── transcript ────────────────────────────────────────────────────────────────

# PATCH2_YTDLP_FETCH
def fetch_transcript(video_id: str, cookies_file: str | None = None) -> tuple[str | None, str]:
    """
    Return (transcript_text, status) where status is one of:
      'ok', 'no_transcript', 'ip_blocked', 'error'

    PRIMARY: yt-dlp subtitle extraction (handles cookies, cloud IPs, all formats)
    FALLBACK: youtube-transcript-api (works without cookies on non-blocked IPs)
    """
    import subprocess
    import tempfile
    import os
    import json as _json

    video_url = f"https://www.youtube.com/watch?v={video_id}"

    # ── PRIMARY: yt-dlp subtitle/caption extraction ───────────────────────────
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd = [
                "yt-dlp",
                "--write-auto-subs",
                "--write-subs",
                "--sub-langs", "en",
                "--sub-format", "json3/vtt/ttml/best",
                "--skip-download",
                "--no-warnings",
                "--quiet",
                "-o", os.path.join(tmpdir, "%(id)s.%(ext)s"),
            ]
            if cookies_file and os.path.exists(cookies_file):
                cmd += ["--cookies", cookies_file]
            cmd.append(video_url)

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            # Find any subtitle file written
            sub_text = ""
            for fname in os.listdir(tmpdir):
                fpath = os.path.join(tmpdir, fname)
                if fname.endswith(".json3"):
                    try:
                        data = _json.loads(open(fpath).read())
                        events = data.get("events", [])
                        parts = []
                        for ev in events:
                            for seg in ev.get("segs", []):
                                t = seg.get("utf8", "").strip()
                                if t and t != "\n":
                                    parts.append(t)
                        sub_text = " ".join(parts)
                    except Exception:
                        pass
                elif fname.endswith(".vtt"):
                    try:
                        raw = open(fpath).read()
                        # Strip VTT headers and timing lines
                        lines = []
                        for line in raw.split("\n"):
                            line = line.strip()
                            if (line.startswith("WEBVTT") or
                                    "-->" in line or
                                    line.startswith("NOTE") or
                                    line == "" or
                                    line.isdigit()):
                                continue
                            # Remove HTML tags
                            import re as _re
                            clean = _re.sub(r"<[^>]+>", "", line).strip()
                            if clean:
                                lines.append(clean)
                        sub_text = " ".join(lines)
                    except Exception:
                        pass
                elif fname.endswith(".ttml"):
                    try:
                        raw = open(fpath).read()
                        import re as _re
                        texts = _re.findall(r">([^<]+)<", raw)
                        sub_text = " ".join(t.strip() for t in texts if t.strip())
                    except Exception:
                        pass

                if sub_text:
                    break

            if sub_text and len(sub_text) > 50:
                return sub_text, "ok"

            # yt-dlp ran but no subtitles found — check stderr for block signals
            stderr = result.stderr.lower()
            if "sign in" in stderr or "bot" in stderr or "429" in stderr:
                # Try fallback before declaring blocked
                pass
            elif result.returncode == 0:
                # Ran fine, just no subtitles available
                pass

    except subprocess.TimeoutExpired:
        pass
    except Exception as _ytdlp_err:
        pass

    # ── FALLBACK: youtube-transcript-api ─────────────────────────────────────
    if _YT_TRANSCRIPT_API_AVAILABLE:
        try:
            api = YouTubeTranscriptApi()
            result_api = api.fetch(video_id)
            text = " ".join(seg.text for seg in result_api)
            if text:
                return text, "ok"
        except RequestBlocked:
            return None, "ip_blocked"
        except (NoTranscriptFound, TranscriptsDisabled):
            return None, "no_transcript"
        except Exception as exc:
            err = str(exc)
            if "Sign in" in err or "bot" in err.lower() or "blocked" in err.lower():
                return None, "ip_blocked"

    return None, "no_transcript"


# ── NLP helpers ───────────────────────────────────────────────────────────────

def extract_keywords(text: str, top_n: int = 15) -> list[str]:
    """Frequency-based keyword extraction — no LLM required."""
    words = re.findall(r"[a-zA-Z']{3,}", text.lower())
    filtered = [w.strip("'") for w in words if w not in STOP_WORDS and len(w) >= 3]
    counter = Counter(filtered)
    return [word for word, _ in counter.most_common(top_n)]


def build_summary(text: str, keywords: list[str], max_sentences: int = 3) -> str:
    """
    Extractive summary: score sentences by keyword density, return top ones.
    Falls back to first 300 chars if no sentences score well.
    """
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    if not sentences:
        return text[:300]

    keyword_set = set(keywords[:10])

    def score(sent: str) -> float:
        words = set(re.findall(r"[a-zA-Z']{3,}", sent.lower()))
        return len(words & keyword_set) / (len(words) + 1)

    scored = sorted(enumerate(sentences), key=lambda x: score(x[1]), reverse=True)
    top_indices = sorted(i for i, _ in scored[:max_sentences])
    summary = " ".join(sentences[i] for i in top_indices).strip()

    if not summary or len(summary) < 20:
        summary = text[:300]

    return summary


def clean_transcript(text: str) -> str:
    """Remove common auto-caption artefacts."""
    text = re.sub(r"\[.*?\]", " ", text)          # [Music], [Applause] etc.
    text = re.sub(r"\(.*?\)", " ", text)           # (inaudible) etc.
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ── main analysis ─────────────────────────────────────────────────────────────

def analyze_video(meta: dict, cookies_file: str | None = None) -> dict:
    """
    Fetch transcript for a video and return enriched result dict.
    """
    result = {
        "title": meta["title"],
        "url": meta["url"],
        "channel": meta["channel"],
        "views": meta["views"],
        "duration": meta["duration"],
        "transcript_snippet": None,
        "content_summary": None,
        "key_topics": [],
        "transcript_available": False,
        "transcript_status": None,
    }

    raw, status = fetch_transcript(meta["video_id"], cookies_file)
    result["transcript_status"] = status

    if not raw:
        if status == "ip_blocked":
            result["content_summary"] = (
                "transcript unavailable: VPS IP blocked by YouTube. "
                "Provide a cookies.txt file with --cookies to bypass."
            )
        elif status == "no_transcript":
            result["content_summary"] = "no transcript available for this video"
        else:
            result["content_summary"] = f"transcript fetch failed ({status})"
        return result

    text = clean_transcript(raw)
    result["transcript_available"] = True
    result["transcript_snippet"] = text[:500]

    keywords = extract_keywords(text)
    result["key_topics"] = keywords[:10]
    result["content_summary"] = build_summary(text, keywords)

    return result


# ── public API ────────────────────────────────────────────────────────────────

def search_and_analyze(
    query: str,
    max_results: int = 5,
    cookies_file: str | None = None,
) -> list[dict]:
    """
    Search YouTube for *query*, fetch transcripts, return enriched results.
    cookies_file: path to Netscape cookies.txt to bypass cloud IP bans.
    """
    print(f"[youtube_research] Searching YouTube: {query!r} (max {max_results})")
    videos = search_youtube(query, max_results)
    print(f"[youtube_research] Found {len(videos)} videos. Fetching transcripts…")

    results = []
    ip_blocked_count = 0
    for i, meta in enumerate(videos, 1):
        print(f"  [{i}/{len(videos)}] {meta['title'][:60]}")
        enriched = analyze_video(meta, cookies_file)
        if enriched.get("transcript_status") == "ip_blocked":
            ip_blocked_count += 1
        results.append(enriched)

    if ip_blocked_count > 0:
        print(
            f"\n  [WARNING] {ip_blocked_count}/{len(videos)} videos had transcripts blocked "
            f"(cloud IP ban). Pass cookies_file= or --cookies <path> to bypass."
        )

    return results


def save_results(results: list[dict], query: str, output_path: Path | None = None) -> Path:
    """Save results JSON to reports dir and return the path."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    if output_path is None:
        output_path = REPORTS_DIR / f"youtube_research_{ts}.json"

    payload = {
        "query": query,
        "timestamp": ts,
        "result_count": len(results),
        "results": results,
    }
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return output_path


def print_human_readable(results: list[dict], query: str) -> None:
    """Print a human-friendly summary to stdout."""
    print(f"\n{'='*70}")
    print(f"YouTube Research Results — {query!r}")
    print(f"{'='*70}")
    for i, r in enumerate(results, 1):
        views = f"{r['views']:,}" if r.get("views") else "N/A"
        dur = f"{int(r['duration'])//60}m {int(r['duration'])%60}s" if r.get("duration") else "N/A"
        print(f"\n[{i}] {r['title']}")
        print(f"    URL     : {r['url']}")
        print(f"    Channel : {r['channel']}  |  Views: {views}  |  Duration: {dur}")
        if r["transcript_available"]:
            print(f"    Topics  : {', '.join(r['key_topics'])}")
            print(f"    Summary : {r['content_summary'][:200]}")
        else:
            print(f"    Transcript: {r['content_summary']}")
    print(f"\n{'='*70}\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="YouTube research tool — search + transcript analysis")
    parser.add_argument("query", nargs="?", help="Search query")
    parser.add_argument("--query", dest="query_flag", help="Search query (alias for positional arg)")
    parser.add_argument("--max-results", type=int, default=5, help="Max videos to fetch (default: 5)")
    parser.add_argument("--output", help="Path to save JSON output (optional)")
    parser.add_argument("--json-only", action="store_true", help="Print only JSON to stdout")
    parser.add_argument(
        "--cookies",
        dest="cookies_file",
        help="Path to Netscape cookies.txt to bypass YouTube cloud IP bans",
    )

    args = parser.parse_args()
    query = args.query or args.query_flag
    if not query:
        parser.error("Provide a search query as positional arg or --query")

    results = search_and_analyze(query, args.max_results, getattr(args, "cookies_file", None))

    out_path = Path(args.output) if args.output else None
    saved = save_results(results, query, out_path)
    print(f"\n[youtube_research] Results saved → {saved}")

    if args.json_only:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print_human_readable(results, query)


if __name__ == "__main__":
    main()
