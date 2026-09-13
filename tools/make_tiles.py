"""Генерация офлайн XYZ-тайлов (подложка для Leaflet).

В песочнице нет доступа к tile.openstreetmap.org, поэтому подложка рисуется
локально из береговых линий и границ GSHHS (пакет basemap-data) и режется на
тайлы 256×256. В обычном окружении этот скрипт не нужен — в LEAFLET_CONFIG
ставится обычный OSM-слой.

Запуск: python tools/make_tiles.py [max_zoom]
"""

import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from mpl_toolkits.basemap import Basemap  # noqa: E402
from PIL import Image  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "static" / "tiles"
TILE = 256
MAX_ZOOM = int(sys.argv[1]) if len(sys.argv) > 1 else 7
# Европейская часть России — регион демо-данных
BBOX = (22.0, 44.0, 62.0, 66.0)  # lon_min, lat_min, lon_max, lat_max

LAND = "#eef1ec"
WATER = "#dbe7f0"
COAST = "#b8c6cf"
BORDER = "#c9c2b6"


def deg2num(lon, lat, z):
    n = 2**z
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def num2deg(x, y, z):
    n = 2**z
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lon, lat


def render(zoom):
    """Рисует один Mercator-холст на зум и режет его на тайлы."""
    x0, y1 = deg2num(BBOX[0], BBOX[1], zoom)
    x1, y0 = deg2num(BBOX[2], BBOX[3], zoom)
    tx0, tx1 = int(math.floor(x0)), int(math.ceil(x1))
    ty0, ty1 = int(math.floor(y0)), int(math.ceil(y1))

    lon_min, lat_max = num2deg(tx0, ty0, zoom)
    lon_max, lat_min = num2deg(tx1, ty1, zoom)
    width, height = (tx1 - tx0) * TILE, (ty1 - ty0) * TILE

    dpi = 100
    fig = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    m = Basemap(
        projection="merc",
        llcrnrlon=lon_min,
        llcrnrlat=lat_min,
        urcrnrlon=lon_max,
        urcrnrlat=lat_max,
        resolution="l" if zoom < 6 else "i",
        ax=ax,
    )
    m.drawmapboundary(fill_color=WATER)
    m.fillcontinents(color=LAND, lake_color=WATER)
    m.drawcoastlines(linewidth=0.5, color=COAST)
    m.drawcountries(linewidth=0.7, color=BORDER)
    if zoom >= 5:
        m.drawrivers(linewidth=0.4, color="#c6d9e6")
    ax.set_axis_off()

    canvas = Path("/tmp/_tiles_canvas.png")
    fig.savefig(canvas, dpi=dpi, pad_inches=0)
    plt.close(fig)

    img = Image.open(canvas).convert("RGB").resize((width, height))
    count = 0
    for tx in range(tx0, tx1):
        for ty in range(ty0, ty1):
            left, top = (tx - tx0) * TILE, (ty - ty0) * TILE
            tile = img.crop((left, top, left + TILE, top + TILE))
            path = OUT / str(zoom) / str(tx)
            path.mkdir(parents=True, exist_ok=True)
            tile.save(path / f"{ty}.png", optimize=True)
            count += 1
    print(f"zoom {zoom}: {count} тайлов ({width}×{height} px)")


if __name__ == "__main__":
    for z in range(3, MAX_ZOOM + 1):
        render(z)
    print(f"Готово: {OUT}")
