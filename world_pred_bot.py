"""
Kicktipp WorldPrediction2026 — Telegram Bot
/leaderboard — shows the prediction matrix exactly as on the website
/bonus       — shows the bonus questions matrix
"""

import os
import re
import logging
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
URL = "https://www.kicktipp.com/worldprediction2026/leaderboard"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.kicktipp.com/",
}

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def parse_header_cell(cell):
    """
    Parse a header cell like 'MEXRSA2-0' or 'QATCH---' into (label, result).
    Format: TEAM1(3chars) + TEAM2(2-4chars) + score_or_dashes
    """
    m = re.match(r'^([A-Z]+)([\d]+-[\d]+|---)$', cell)
    if not m:
        return None, None
    teams  = m.group(1)
    result = m.group(2)
    t1 = teams[:3]
    t2 = teams[3:]
    if not t2:
        return None, None
    return f"{t1} {t2}", result


def split_pred(raw):
    """
    Kicktipp concatenates prediction + points earned into one string:
      '2-09' -> pred='2-0', pts='9'
      '1-03' -> pred='1-0', pts='3'
      '2-19' -> pred='2-1', pts='9'
      '1-1'  -> pred='1-1', pts=''   (match not finished yet)
      '---'  -> pred='---', pts=''
      ''     -> pred='-',   pts=''
    Rule: away score is always exactly 1 digit; extra digits are points.
    """
    raw = raw.strip()
    if not raw or raw == "---":
        return raw or "-", ""
    m = re.match(r'^(\d+)-(\d+)$', raw)
    if m:
        home     = m.group(1)
        away_pts = m.group(2)
        if len(away_pts) > 1:
            return f"{home}-{away_pts[0]}", away_pts[1:]
        return f"{home}-{away_pts}", ""
    return raw, ""


def split_bonus(raw):
    """
    Split a bonus answer cell into (answer, points_earned).

    Kicktipp concatenates the answer and points:
      'GER9'   -> answer='GER',    pts='9'
      'France' -> answer='France',  pts=''  (not yet scored)
      '127'    -> answer='127',     pts=''  (numeric answer, not scored)
      '---'    -> answer='---',     pts=''
      ''       -> answer='-',       pts=''
    """
    raw = raw.strip()
    if not raw or raw in ("---", "-"):
        return raw or "-", ""
    # Purely numeric → treat as answer, not points
    if raw.isdigit():
        return raw, ""
    # Text ending with 1-2 digits → split as answer + points
    m = re.match(r'^(.+?)(\d{1,2})$', raw)
    if m and not m.group(1).isdigit():
        return m.group(1), m.group(2)
    return raw, ""


# ---------------------------------------------------------------------------
# /leaderboard
# ---------------------------------------------------------------------------

def fetch_matrix():
    r = requests.get(URL, headers=HEADERS, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    match_labels  = []
    match_results = []
    players = []

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue

        # Find the header row: contains cells matching TEAM1TEAM2score pattern
        header_row  = None
        num_matches = 0

        for row in rows:
            cells = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
            labels, results = [], []
            for cell in cells:
                label, result = parse_header_cell(cell)
                if label:
                    labels.append(label)
                    results.append(result)
            if labels:
                match_labels  = labels
                match_results = results
                num_matches   = len(labels)
                header_row    = row
                break

        if not header_row:
            continue

        # Parse player rows
        for row in rows:
            if row is header_row:
                continue
            cells = [c.get_text(strip=True) for c in row.find_all("td")]
            if len(cells) < 4:
                continue
            pos = cells[0].replace(".", "").strip()
            if not pos.isdigit():
                continue
            name = cells[2].strip()
            if not name:
                continue

            preds = []
            pts_list = []
            for i in range(num_matches):
                col = 3 + i
                raw = cells[col] if col < len(cells) else ""
                pred, pts = split_pred(raw)
                preds.append(pred)
                pts_list.append(pts)

            total  = cells[-1].strip() if cells else "0"

            players.append({
                "pos":    int(pos),
                "name":   name,
                "preds":  preds,
                "pts":    pts_list,
                "total":  total  or "0",
            })

        if players:
            break

    return match_labels, match_results, players


def build_table(match_labels, match_results, players):
    if not match_labels or not players:
        return "⚠️ No data found. Try again later."

    name_w = 7   # truncate names to 7 chars
    col_w  = 3   # "2-0" and "---" are both 3 chars

    home_teams = [lbl.split()[0][:3] for lbl in match_labels]
    away_teams = [lbl.split()[1][:3] if len(lbl.split()) > 1 else "   " for lbl in match_labels]

    def make_row(name_col, pred_cols, tot_col):
        return (
            name_col[:name_w].ljust(name_w) + " "
            + " ".join(c.center(col_w) for c in pred_cols)
            + f" {tot_col:>2}"
        )

    header1 = make_row("",      home_teams,    " ")
    header2 = make_row("",      away_teams,    "T")
    score_r = make_row("Score", match_results, " ")
    divider = "-" * len(header1)

    lines = ["🏆 *WorldPrediction2026*\n", "```"]
    lines.append(header1)
    lines.append(header2)
    lines.append(score_r)
    lines.append(divider)

    for p in players:
        preds = [p["preds"][i] if i < len(p["preds"]) else "-" for i in range(len(match_labels))]
        lines.append(make_row(p["name"], preds, p["total"]))

    lines.append("```")
    lines.append("_\\- = no prediction yet · T = total_")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# /bonus
# ---------------------------------------------------------------------------

def fetch_bonus_matrix():
    """Fetch and parse the bonus questions leaderboard page."""
    r = requests.get(URL + "?bonus=true", headers=HEADERS, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    bonus_labels    = []
    correct_answers = []
    players         = []

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue

        header_row = None
        num_bonus  = 0

        # Identify header row: cells 3+ contain bonus question labels
        for row in rows:
            cells = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
            if len(cells) < 4:
                continue
            labels = cells[3:]
            non_empty = [l for l in labels if l.strip()]
            if not non_empty:
                continue
            # Skip rows that look like match-prediction headers
            if any(re.match(r'^[A-Z]+(\d+-\d+|---)$', l) for l in labels):
                continue
            bonus_labels = labels
            num_bonus    = len(labels)
            header_row   = row
            break

        if not header_row:
            continue

        # Collect rows after the header
        remaining = [row for row in rows if row is not header_row]

        # Check if the first remaining row is a "correct answer" row
        if remaining:
            first_cells = [c.get_text(strip=True) for c in remaining[0].find_all(["th", "td"])]
            first_pos = first_cells[0].replace(".", "").strip() if first_cells else ""
            if not first_pos.isdigit() and len(first_cells) >= 4:
                correct_answers = first_cells[3:3 + num_bonus]
                remaining = remaining[1:]

        # Parse player rows
        for row in remaining:
            cells = [c.get_text(strip=True) for c in row.find_all("td")]
            if len(cells) < 4:
                continue
            pos = cells[0].replace(".", "").strip()
            if not pos.isdigit():
                continue
            name = cells[2].strip()
            if not name:
                continue

            answers  = []
            pts_list = []
            for i in range(num_bonus):
                col = 3 + i
                raw = cells[col] if col < len(cells) else ""
                answer, pts = split_bonus(raw)
                answers.append(answer)
                pts_list.append(pts)

            total = cells[-1].strip() if cells else "0"

            players.append({
                "pos":     int(pos),
                "name":    name,
                "answers": answers,
                "pts":     pts_list,
                "total":   total or "0",
            })

        if players:
            break

    return bonus_labels, correct_answers, players


def build_bonus_table(bonus_labels, correct_answers, players):
    """Build a monospace table string for the bonus leaderboard."""
    if not bonus_labels or not players:
        return "⚠️ No bonus data found. Try again later."

    name_w = 7
    col_w  = 7   # wider than match cols to fit text answers

    def make_row(name_col, data_cols, tot_col):
        return (
            name_col[:name_w].ljust(name_w) + " "
            + " ".join(c[:col_w].center(col_w) for c in data_cols)
            + f" {tot_col:>2}"
        )

    header  = make_row("",       bonus_labels,    "T")
    divider = "-" * len(header)

    lines = ["🏆 *WorldPrediction2026 — Bonus*\n", "```"]
    lines.append(header)

    if correct_answers:
        lines.append(make_row("Answer", correct_answers, " "))

    lines.append(divider)

    for p in players:
        answers = [
            p["answers"][i] if i < len(p["answers"]) else "-"
            for i in range(len(bonus_labels))
        ]
        lines.append(make_row(p["name"], answers, p["total"]))

    lines.append("```")
    lines.append("_\\- = no answer yet · T = total bonus pts_")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Bot commands
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *WorldPrediction2026 Bot*\n\n"
        "Use /leaderboard to see the prediction matrix.\n"
        "Use /bonus to see bonus question answers.\n\n"
        "Type /help for all commands.",
        parse_mode="Markdown"
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Commands*\n\n"
        "/leaderboard — Full prediction matrix showing everyone's tips "
        "for each match, the actual score, and current points\n\n"
        "/bonus — Bonus questions matrix showing everyone's answers "
        "to bonus questions and points earned\n\n"
        "/start — Welcome message\n\n"
        "/help — This message",
        parse_mode="Markdown"
    )


async def cmd_leaderboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching…")
    try:
        match_labels, match_results, players = fetch_matrix()
        text = build_table(match_labels, match_results, players)
    except Exception as e:
        logger.error(e)
        text = f"❌ Error: {e}"
    for chunk in [text[i:i+4096] for i in range(0, len(text), 4096)]:
        await update.message.reply_text(chunk, parse_mode="Markdown")


async def cmd_bonus(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching bonus…")
    try:
        bonus_labels, correct_answers, players = fetch_bonus_matrix()
        text = build_bonus_table(bonus_labels, correct_answers, players)
    except Exception as e:
        logger.error(e)
        text = f"❌ Error: {e}"
    for chunk in [text[i:i+4096] for i in range(0, len(text), 4096)]:
        await update.message.reply_text(chunk, parse_mode="Markdown")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("⚠️  Set TELEGRAM_BOT_TOKEN env var or paste your token into BOT_TOKEN.")
        return
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("help",        cmd_help))
    app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    app.add_handler(CommandHandler("bonus",       cmd_bonus))
    logger.info("Bot is running…")
    app.run_polling()


if __name__ == "__main__":
    main()
