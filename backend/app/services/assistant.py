"""The "Ask" assistant: Claude answers questions about your portfolio by calling the what-if engine.

Every number in an answer comes from a tool result computed by the app; the model explains, it doesn't calculate.
Data sent to Anthropic: your question and the tool results it asks for (stock names, shares, prices, gains in USD).
Nothing is executed: the tools only simulate.
"""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy.orm import Session

from app.db import models as m

from . import portfolio as P
from . import whatif as WS
from .portfolio import BadRequest, NotFound

MODEL = WS.MODEL
MAX_ROUNDS = 10

SYSTEM = """You are the assistant inside Portfolio Tracker, a personal app that tracks one person's stock trades. \
You answer questions about their portfolio and preview "what if" scenarios: selling now (one stock, several, a sector \
or everything) and rebalancing.

Rules:
- Get every figure from the tools. Never estimate, recompute or invent prices, gains, weights or totals; quote what the \
tools return (rounded sensibly, in USD). If a tool returns an error, explain it plainly and say what the user can do.
- Resolve stock names with find_positions before simulating; if several positions match, ask which one is meant.
- Sectors are the ones the user confirmed in the app. If a sector question finds none, say sectors can be set on the \
Names page.
- All results are before tax and are simulations: nothing is sold, bought or saved. Say so briefly when you show a \
simulated trade. You cannot place orders.
- This is information, not investment advice: don't recommend buying or selling; you may point out facts the numbers \
show (e.g. which positions carry losses).
- For "buy more to lower my loss / average down" questions use simulate_average_down. Show the trade-off both ways: the \
lower break-even and smaller rise needed, AND the extra money at risk (the loss if it falls a further 20%, with vs \
without buying). Mention that break-even is for selling the whole position and FIFO sells the oldest shares first. \
Don't say whether the stock will recover or whether to buy; that judgement is the user's.
- Gains use FIFO (oldest purchases sold first) and include the currency effect, like the rest of the app.
- Be concise: lead with the answer, then a short breakdown (a small table is fine), then one line of caveats."""

_obj = lambda props, req: {"type": "object", "properties": props, "required": req, "additionalProperties": False}  # noqa: E731
_null = lambda schema: {"anyOf": [schema, {"type": "null"}]}  # noqa: E731  (strict schemas: anyOf, not type arrays)

TOOLS = [
    {"name": "get_portfolio", "strict": True,
     "description": "Current open positions (stock, pool id, sector, shares, price, value, FIFO cost, unrealised gain, weight), "
                    "value by sector, total value and realised gain so far this year. Use for any question about holdings.",
     "input_schema": _obj({}, [])},
    {"name": "find_positions", "strict": True,
     "description": "Find open positions whose name matches the words given (e.g. 'microsoft', 'alphabet'). Returns pool ids to "
                    "use in the other tools.",
     "input_schema": _obj({"query": {"type": "string", "description": "Words from the stock name"}}, ["query"])},
    {"name": "simulate_sale", "strict": True,
     "description": "Simulate selling now, FIFO, before tax. Give EITHER items (specific positions, each with shares OR percent; "
                    "both null = all shares), OR sector (a confirmed sector name), OR everything=true; percent applies to the "
                    "sector/everything case (null = 100). Returns proceeds, FIFO cost, gain per position and per purchase lot, "
                    "split by holding period, totals, and realised gain for this year before and after.",
     "input_schema": _obj({
         "items": _null({"type": "array", "items": _obj({
             "pool": {"type": "string", "description": "pool id from get_portfolio / find_positions"},
             "shares": _null({"type": "number"}), "percent": _null({"type": "number"})}, ["pool", "shares", "percent"])}),
         "sector": _null({"type": "string"}),
         "everything": {"type": "boolean"},
         "percent": _null({"type": "number"})}, ["items", "sector", "everything", "percent"])},
    {"name": "simulate_rebalance", "strict": True,
     "description": "Preview rebalancing to target weights (% of today's portfolio value) by stock (keys = pool ids) or by "
                    "sector (keys = sector names). Positions without a target stay as they are. Returns the trades (whole "
                    "shares), the gain realised by the sales (FIFO, before tax), cash raised or needed, and weights before/after.",
     "input_schema": _obj({
         "by": {"type": "string", "enum": ["stock", "sector"]},
         "targets": {"type": "array", "items": _obj({"key": {"type": "string"}, "percent": {"type": "number"}}, ["key", "percent"])}},
         ["by", "targets"])},
    {"name": "simulate_average_down", "strict": True,
     "description": "Break-even maths for buying more of an open position (averaging down). Give the pool, optionally a buy price "
                    "in the listing's units (null = today's price; pence for GBP), and AT MOST ONE of shares, amount_usd or "
                    "target_break_even (all null = only the standard table). Returns the position now (break-even, rise needed), the "
                    "plan (new break-even, money needed, rise needed, loss if it falls another 20% with vs without buying, and what "
                    "FIFO realises if only the added shares are sold later), and a table of buy prices (today, -10/-20/-30%) by "
                    "size (+50%, +100%, +200% of current shares).",
     "input_schema": _obj({
         "pool": {"type": "string", "description": "pool id from get_portfolio / find_positions"},
         "buy_price": _null({"type": "number"}), "shares": _null({"type": "number"}),
         "amount_usd": _null({"type": "number"}), "target_break_even": _null({"type": "number"})},
         ["pool", "buy_price", "shares", "amount_usd", "target_break_even"])},
    {"name": "get_realised_by_year", "strict": True,
     "description": "Realised gains per calendar year (FIFO, USD): sales, gain, wins and losses.",
     "input_schema": _obj({}, [])},
]


def _round(x):
    if isinstance(x, float):
        return round(x, 2)
    if isinstance(x, dict):
        return {k: _round(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_round(v) for v in x]
    return x


def run_tool(db: Session, name: str, args: dict) -> tuple[str, bool]:
    """Returns (JSON text, is_error)."""
    try:
        if name == "get_portfolio":
            o = WS.overview(db)
            o["holdings"] = [{k: h[k] for k in ("pool", "stock", "sector", "currency", "shares", "price", "value_usd",
                                                 "cost_usd", "unrealised_usd", "weight_pct", "price_date")} for h in o["holdings"]]
            res = o
        elif name == "find_positions":
            res = {"matches": WS.find(db, args.get("query", ""))}
        elif name == "simulate_sale":
            res = WS.simulate_sale(db, items=args.get("items"), sector=args.get("sector"),
                                   everything=bool(args.get("everything")), percent=args.get("percent"))
            for s in res["sales"]:
                s["lots"] = s["lots"][:12] + ([{"more_lots": len(s["lots"]) - 12}] if len(s["lots"]) > 12 else [])
        elif name == "simulate_rebalance":
            res = WS.simulate_rebalance(db, args["by"], {t["key"]: t["percent"] for t in args.get("targets", [])})
            if res.get("sale"):
                for s in res["sale"]["sales"]:
                    s.pop("lots", None)
        elif name == "simulate_average_down":
            res = WS.simulate_average_down(db, args["pool"], args.get("buy_price"), args.get("shares"), args.get("amount_usd"),
                                           args.get("target_break_even"))
        elif name == "get_realised_by_year":
            res = {"years": P.sales(db)["by_year"]}
        else:
            return json.dumps({"error": f"unknown tool {name}"}), True
        return json.dumps(_round(res), default=str), False
    except (BadRequest, NotFound) as e:
        return json.dumps({"error": str(e)}), True
    except (KeyError, TypeError, ValueError) as e:
        return json.dumps({"error": f"bad input: {e}"}), True


def status() -> dict:
    return {"available": WS.ai_available(), "model": MODEL,
            "setup": "Add ANTHROPIC_API_KEY=… to the .env file in the app's folder (copy .env.example), then restart the app."}


def _block_dict(b) -> dict:
    return b.to_dict() if hasattr(b, "to_dict") else dict(b)


def ask(db: Session, question: str, chat_id: int | None = None) -> dict:
    import anthropic
    question = (question or "").strip()
    if not question:
        raise BadRequest("Type a question.")
    if len(question) > 4000:
        raise BadRequest("The question is too long (4,000 characters at most).")
    if not WS.ai_available():
        raise BadRequest("The assistant needs an Anthropic API key. " + status()["setup"])
    P._need(db)
    chat = db.get(m.AssistantChat, chat_id) if chat_id else None
    if chat_id and chat is None:
        raise NotFound(f"conversation {chat_id} not found")
    if chat is None:
        chat = m.AssistantChat(messages=[], display=[])
        db.add(chat)
        db.flush()
    messages = list(chat.messages) + [{"role": "user", "content": question}]
    shown = list(chat.display) + [{"role": "user", "text": question}]
    calls: list[dict] = []
    client = WS.make_client()
    today = date.today().isoformat()
    final_text, stop = "", None
    for _ in range(MAX_ROUNDS):
        try:
            resp = client.beta.messages.create(
                model=MODEL, max_tokens=16000, system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
                tools=TOOLS, messages=messages, output_config={"effort": "medium"},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                metadata={"user_id": "portfolio-tracker-local"})
        except anthropic.AuthenticationError as e:
            raise BadRequest("The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in the app's .env file.") from e
        except anthropic.RateLimitError as e:
            raise BadRequest("Anthropic's API is rate-limiting this key right now; try again in a minute.") from e
        except anthropic.APIConnectionError as e:
            raise BadRequest("Couldn't reach Anthropic's API. Check your internet connection.") from e
        except anthropic.APIStatusError as e:
            raise BadRequest(f"Anthropic's API answered {e.status_code}: {e.message}") from e
        except Exception as e:  # anything else: a readable message, never a bare 500
            raise BadRequest(f"The assistant hit an unexpected problem ({type(e).__name__}). Try again.") from e
        stop = resp.stop_reason
        messages.append({"role": "assistant", "content": [_block_dict(b) for b in resp.content]})  # unchanged, append-only
        if stop == "pause_turn":
            continue
        uses = [b for b in resp.content if b.type == "tool_use"]
        if stop == "tool_use" and uses:
            results = []
            for u in uses:
                text, err = run_tool(db, u.name, dict(u.input) if isinstance(u.input, dict) else {})
                calls.append({"tool": u.name, "input": u.input, "error": err, "result": json.loads(text)})
                results.append({"type": "tool_result", "tool_use_id": u.id, "content": text, **({"is_error": True} if err else {})})
            messages.append({"role": "user", "content": results})
            continue
        final_text = "\n".join(b.text for b in resp.content if b.type == "text").strip()
        break
    else:
        final_text = "I stopped after too many steps without an answer. Try asking a narrower question."
    if stop == "refusal":
        final_text = "This question was declined by the model's safety checks. Try rephrasing it."
    elif stop == "max_tokens" and not final_text:
        final_text = "The answer was cut off. Try a narrower question."
    shown.append({"role": "assistant", "text": final_text or "(no answer)", "calls": calls, "date": today})
    chat.messages, chat.display = messages, shown
    db.commit()
    return {"chat_id": chat.id, "display": shown}


def get_chat(db: Session, chat_id: int) -> dict:
    chat = db.get(m.AssistantChat, chat_id)
    if chat is None:
        raise NotFound(f"conversation {chat_id} not found")
    return {"chat_id": chat.id, "display": chat.display}
