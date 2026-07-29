# Who Dis? — Discord Bot

A Discord bot for **Who Dis?**, an Apples-to-Apples-style party game where a
Judge reads an "Inbox" text message and everyone else submits a "Reply" card
they think fits best. One deck: 148 Inbox cards / 275 Reply cards.

## 1. Create the Discord bot

1. Go to https://discord.com/developers/applications → **New Application**.
2. Under **Bot**, click **Reset Token** / **Copy** to get your bot token.
3. Under **Bot**, no privileged intents are required (the bot only uses
   slash commands and message content it's shown directly), but you can
   leave the default intents as-is.
4. Under **OAuth2 → URL Generator**, check scopes `bot` and
   `applications.commands`, then under **Bot Permissions** check:
   `Send Messages`, `Embed Links`, `Read Message History`, `Use Slash Commands`.
5. Open the generated URL to invite the bot to your server.

## 2. Run the bot

```bash
cd whodis_bot
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export DISCORD_BOT_TOKEN="your-bot-token-here"   # Windows (PowerShell): $env:DISCORD_BOT_TOKEN="..."
python3 bot.py
```

The first time it connects it will sync slash commands globally — this can
take up to an hour to show up everywhere the first time, but usually appears
within a few minutes.

## 3. How to play in Discord

| Command | Who uses it | What it does |
|---|---|---|
| `/whodis-rules` | Anyone, anytime | Shows a short "How to Play" summary (with a **Got it, skip** button). |
| `/whodis-start points` | Anyone | Opens a lobby in the current channel. Choose points to win (3/5/7/10). |
| **Join Game** button | Everyone playing | Tap the button on the lobby message to join. |
| **How to Play** button | Anyone | Same rules summary, right from the lobby message — skip it if you already know how to play. |
| `/whodis-join` | Everyone playing | Alternative to the button, joins via slash command. |
| `/whodis-leave` | Anyone in lobby | Leave before the game starts. |
| `/whodis-begin` | Lobby host | Deals 7 Reply cards to everyone and starts Round 1 (needs 3+ players). |
| `/submit` | Non-judge players, each round | Private (ephemeral) message showing an image of your hand — pick your reply from the dropdown. |
| `/vote` | The current Judge only | Once everyone's submitted, shows an image grid of the anonymized replies — pick the winner from the dropdown. |
| `/whodis-scores` | Anyone | Shows the live scoreboard. |
| `/whodis-end` | Host or a server manager | Cancels the game in this channel. |

### Round flow
1. Bot posts the Inbox card as an image and names the Judge.
2. Everyone except the Judge runs `/submit` and privately picks a Reply card from an image of their hand.
3. Once all replies are in, the bot pings the Judge to run `/vote`.
4. The Judge sees a numbered image grid of the anonymized replies and picks a winner from the dropdown.
5. The bot announces the winner with a side-by-side image of the Inbox message and the winning Reply, awards a point, refills hands, and — unless someone just hit the points target — starts the next round with the next player as Judge (rotates in join order).
6. First to the target score wins; final scoreboard is posted and the game in that channel is cleared.

## Card art & color scheme

- Every one of the 424 cards (148 Inbox + 275 Reply, plus the card back) is
  individually rendered as a PNG built around `WhoDis?Logo.png`: a bold
  rounded double-line frame (red for Inbox, green for Reply), the logo's
  mascot icon + a label pill up top, and the full logo as a small watermark
  on fronts / large and centered on the uniform card **back** (only ever
  shown to other players — your own hand always shows fronts, with the
  actual text).
- Text/UI colors use the brand palette sourced from the logo: red
  `#A40607`, dark green `#07504E`, and yellow `#FEC103` — used for card
  labels/pills and for the bot's embed accent colors (red for new rounds,
  yellow for round results, green for the lobby and rules).
- Regenerate art any time after editing `inbox-cards.csv` / `reply-cards.csv`
  (project root) or the design in `generate_card_images.py`:
  ```bash
  python3 parse_cards.py           # re-parse the two CSVs -> data/deck.json
  python3 generate_card_images.py  # re-render all card PNGs (resumable)
  ```

## Notes

- **One game per channel** at a time; state is in-memory only (resets if the
  bot restarts).
- Works with 3–20 players; best with 4–8.
- The bot never DMs players — everything happens via ephemeral (private)
  slash command responses, so no DM permissions are needed.
- Card data lives in `data/deck.json`, built from `inbox-cards.csv` and
  `reply-cards.csv` in the project root (regenerate via `python3
  parse_cards.py` if you ever edit those files). Older Normal/Kids deck data
  and card art have been archived under `data/_archive_old/`, not deleted.
