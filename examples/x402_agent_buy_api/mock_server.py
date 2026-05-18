#!/usr/bin/env python3
"""Minimal x402-paid API for local demos (Phase 2)."""

from __future__ import annotations

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from sdk.x402.middleware import build_payment_required_header

PAY_TO = "0x" + "d" * 40
RESOURCE = "http://127.0.0.1:9402/paid"


async def paid(request: Request):
    sig = request.headers.get("PAYMENT-SIGNATURE")
    if sig:
        return JSONResponse({"message": "premium data", "paid": True})
    return JSONResponse(
        status_code=402,
        content={"error": "payment_required"},
        headers={
            "PAYMENT-REQUIRED": build_payment_required_header(
                resource_url=RESOURCE,
                pay_to=PAY_TO,
                amount_atomic="1000000",
            )
        },
    )


app = Starlette(routes=[Route("/paid", paid)])

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9402)
