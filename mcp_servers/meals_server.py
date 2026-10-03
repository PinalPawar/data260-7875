"""
HW5 Part 2A: TheMealDB tutorial MCP server.

A local MCP server named "meals" with four tools that search and fetch
recipes from the public TheMealDB API (test key "1", no sign-up needed).

Run it in the MCP Inspector from the repo root:
    mcp dev mcp_servers/meals_server.py

Logging rule: this server talks to its client over STDIO, so stdout is
reserved for the JSON-RPC messages. Every log line goes to stderr.
"""
import logging
import sys
from typing import Annotated, Any

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import Field

API_BASE = "https://www.themealdb.com/api/json/v1/1"
TIMEOUT_SECONDS = 10.0

logging.basicConfig(
    stream=sys.stderr,  # never stdout -- that would corrupt the JSON-RPC stream
    level=logging.INFO,
    format="%(asctime)s [meals] %(levelname)s %(message)s",
)
log = logging.getLogger("meals")

mcp = FastMCP("meals")


async def _get(path: str, params: dict | None = None) -> dict:
    """Call one TheMealDB endpoint and return its JSON, or raise a clean error."""
    url = f"{API_BASE}/{path}"
    log.info("GET %s params=%s", url, params)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    except httpx.TimeoutException:
        raise RuntimeError(f"TheMealDB did not answer within {TIMEOUT_SECONDS:.0f} seconds")
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"TheMealDB returned HTTP {exc.response.status_code}")
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Network error calling TheMealDB: {type(exc).__name__}")
    except ValueError:
        raise RuntimeError("TheMealDB returned a response that is not valid JSON")


def _meals(payload: dict) -> list[dict]:
    """TheMealDB sends {"meals": null} when nothing matches -> treat as empty."""
    meals = payload.get("meals")
    return meals if isinstance(meals, list) else []


def _details(meal: dict) -> dict[str, Any]:
    """Reshape one raw TheMealDB meal into the meal_details output shape."""
    ingredients = []
    for i in range(1, 21):  # the API uses strIngredient1..20 / strMeasure1..20
        name = (meal.get(f"strIngredient{i}") or "").strip()
        measure = (meal.get(f"strMeasure{i}") or "").strip()
        if name:
            ingredients.append({"name": name, "measure": measure})
    return {
        "id": meal.get("idMeal"),
        "name": meal.get("strMeal"),
        "category": meal.get("strCategory"),
        "area": meal.get("strArea"),
        "instructions": meal.get("strInstructions"),
        "image": meal.get("strMealThumb"),
        "source": meal.get("strSource"),
        "youtube": meal.get("strYoutube"),
        "ingredients": ingredients,
    }


@mcp.tool()
async def search_meals_by_name(
    query: Annotated[str, Field(min_length=1, description="Meal name to search for, e.g. Arrabiata")],
    limit: Annotated[int, Field(ge=1, le=25, description="Maximum meals to return (1-25)")] = 5,
) -> dict:
    """Search meals by name. Returns up to `limit` meals as {id, name, area, category, thumb}."""
    meals = _meals(await _get("search.php", {"s": query}))
    if not meals:
        return {"count": 0, "meals": [], "message": "no matches"}
    results = [
        {
            "id": m.get("idMeal"),
            "name": m.get("strMeal"),
            "area": m.get("strArea"),
            "category": m.get("strCategory"),
            "thumb": m.get("strMealThumb"),
        }
        for m in meals[:limit]
    ]
    return {"count": len(results), "meals": results, "message": "ok"}


@mcp.tool()
async def meals_by_ingredient(
    ingredient: Annotated[str, Field(min_length=1, description="Main ingredient, e.g. chicken")],
    limit: Annotated[int, Field(ge=1, le=25, description="Maximum meals to return (1-25)")] = 12,
) -> dict:
    """Filter meals by main ingredient. Returns small cards {id, name, thumb}."""
    meals = _meals(await _get("filter.php", {"i": ingredient}))
    if not meals:
        return {"count": 0, "meals": [], "message": "no matches"}
    results = [
        {"id": m.get("idMeal"), "name": m.get("strMeal"), "thumb": m.get("strMealThumb")}
        for m in meals[:limit]
    ]
    return {"count": len(results), "meals": results, "message": "ok"}


@mcp.tool()
async def meal_details(
    id: Annotated[str | int, Field(description="TheMealDB meal id, e.g. 52771")],
) -> dict:
    """Look up one meal by id and return its full recipe."""
    meals = _meals(await _get("lookup.php", {"i": str(id).strip()}))
    if not meals:
        return {"meal": None, "message": "no matches"}
    return _details(meals[0])


@mcp.tool()
async def random_meal() -> dict:
    """Return one random meal, in the same shape as meal_details."""
    meals = _meals(await _get("random.php"))
    if not meals:
        return {"meal": None, "message": "no matches"}
    return _details(meals[0])


if __name__ == "__main__":
    log.info("starting meals MCP server on STDIO")
    mcp.run(transport="stdio")
