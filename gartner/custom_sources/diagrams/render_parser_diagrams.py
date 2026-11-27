"""Рендер диаграмм универсального парсера (PNG + SVG) в эту же папку."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
W = 2800
BG = (252, 252, 251)
INK = (28, 25, 23)
MUTED = (87, 83, 78)
LINE = (120, 113, 108)
LOCAL = (245, 245, 244)
LOCAL_BD = (168, 162, 158)
LLM = (255, 244, 214)
LLM_BD = (180, 83, 9)
OK = (236, 253, 245)
OK_BD = (4, 120, 87)
NO = (254, 242, 242)
NO_BD = (185, 28, 28)
ACTOR = (231, 229, 228)
FRAG = (241, 245, 249)
FRAG_BD = (148, 163, 184)
WHITE = (255, 255, 255)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
    ]
    bold_c = [
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\calibrib.ttf",
    ]
    for path in bold_c if bold else candidates:
        p = Path(path)
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def text_w(draw: ImageDraw.ImageDraw, text: str, fnt) -> int:
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0]


def text_h(draw: ImageDraw.ImageDraw, text: str, fnt) -> int:
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[3] - box[1]


def wrap(draw, text: str, fnt, max_w: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if text_w(draw, trial, fnt) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [text]


def rounded(draw, xy, fill, outline, r=14, width=2):
    draw.rounded_rectangle(xy, radius=r, fill=fill, outline=outline, width=width)


def arrow(draw, x1, y1, x2, y2, color=LINE, width=2):
    draw.line((x1, y1, x2, y2), fill=color, width=width)
    if abs(x2 - x1) >= abs(y2 - y1):
        direction = 1 if x2 > x1 else -1
        draw.polygon(
            [
                (x2, y2),
                (x2 - 10 * direction, y2 - 5),
                (x2 - 10 * direction, y2 + 5),
            ],
            fill=color,
        )
    else:
        direction = 1 if y2 > y1 else -1
        draw.polygon(
            [
                (x2, y2),
                (x2 - 5, y2 - 10 * direction),
                (x2 + 5, y2 - 10 * direction),
            ],
            fill=color,
        )


def dashed_v(draw, x, y1, y2, color=(214, 211, 209), step=10):
    y = y1
    while y < y2:
        draw.line((x, y, x, min(y + 6, y2)), fill=color, width=1)
        y += step


def save_png(img: Image.Image, name: str):
    path = OUT / name
    img.save(path, "PNG", optimize=True)
    print(f"wrote {path} ({path.stat().st_size // 1024} KB)")


def render_sequence() -> None:
    """UML sequence: Добавить сайт + scrape карточек."""
    h = 3200
    img = Image.new("RGB", (W, h), BG)
    draw = ImageDraw.Draw(img)
    f_title = font(36, True)
    f_sub = font(20)
    f_box = font(18, True)
    f_small = font(15)
    f_msg = font(16)
    f_num = font(14, True)
    f_leg = font(17)

    title = "Универсальный парсер — UML Sequence Diagram"
    draw.text((64, 36), title, fill=INK, font=f_title)
    draw.text(
        (64, 86),
        "gartner/custom_sources · сценарий «Добавить сайт» (POST /api/custom-sources) → краул → scrape → гейты → raw",
        fill=MUTED,
        font=f_sub,
    )

    # Participants
    names = [
        ("User", "Пользователь"),
        ("UI", "Портал UI"),
        ("API", "service.py\nAPI"),
        ("Pipe", "pipeline.py\ndiscover / scrape"),
        ("Crawl", "crawl.py\ncrawl_domain"),
        ("Fetch", "fetch / browser\nHTML"),
        ("LLM", "LLM API\n(4 гейта)"),
        ("Extr", "article_extract\ntrafilatura"),
        ("Disk", "raw + SQLite\ncustom_sources"),
    ]
    n = len(names)
    left = 90
    right = W - 90
    span = right - left
    xs = [int(left + span * (i + 0.5) / n) for i in range(n)]
    head_y = 160
    box_w, box_h = 168, 70
    lifeline_top = head_y + box_h + 16
    lifeline_bot = 2680

    for i, ((short, label), x) in enumerate(zip(names, xs)):
        rounded(
            draw,
            (x - box_w // 2, head_y, x + box_w // 2, head_y + box_h),
            WHITE if short != "LLM" else LLM,
            LLM_BD if short == "LLM" else LOCAL_BD,
            r=12,
        )
        lines = label.split("\n")
        ty = head_y + 12
        for ln in lines:
            tw = text_w(draw, ln, f_box if len(lines) == 1 else f_small)
            draw.text((x - tw // 2, ty), ln, fill=INK, font=f_box if len(lines) == 1 else f_small)
            ty += 20 if len(lines) > 1 else 24
        dashed_v(draw, x, lifeline_top, lifeline_bot)

    # Message list: (from_idx, to_idx, text, kind)
    # kind: sync | ret | note | self | llm
    messages: list[tuple[int, int, str, str]] = [
        (0, 1, "URL домена + «Добавить сайт»", "sync"),
        (1, 2, "POST /api/custom-sources {url}", "sync"),
        (2, 3, "add_custom_source → discover_source()", "sync"),
        (3, 4, "crawl_domain(start_url, llm, budget)", "sync"),
        (4, 5, "fetch_html_safe: главная, robots.txt", "sync"),
        (5, 4, "HTML / cookie-challenge / timeout", "ret"),
        (4, 4, "Семена: sitemap, RSS, /news, /press", "self"),
        (4, 4, "BFS ≤45 URL, глубина ≤3, same_site", "self"),
        (4, 4, "news_score + classify_page (hub/article/rss)", "self"),
        (4, 4, "classify_theme: ключевые слова нефтегаза", "self"),
        (4, 6, "① refine_theme_once — только если hits < 3", "llm"),
        (6, 4, "oilgas / mixed / other (+ domain override)", "ret"),
        (4, 3, "Профиль источника: hubs, candidates, needs_browser", "ret"),
        (3, 3, "alt: theme=other → отказ, источник не сохранён", "note"),
        (3, 5, "scrape_discovered: хабы + RSS → список ссылок", "sync"),
        (5, 3, "HTML хаба (Playwright, если needs_browser)", "ret"),
        (3, 3, "loop: каждая страница-кандидат (до 8 / 40)", "note"),
        (3, 5, "fetch страницы-кандидата", "sync"),
        (5, 3, "HTML карточки", "ret"),
        (3, 3, "resolve_page_kind / classify_page", "self"),
        (3, 6, "② classify_kind_llm — только спорный URL (бюджет 8)", "llm"),
        (6, 3, "article / hub / junk", "ret"),
        (3, 3, "если не article → skip (не извлекать)", "note"),
        (3, 7, "extract_article_page: trafilatura + BS fallback", "sync"),
        (7, 3, "title, text (≥~200), date", "ret"),
        (3, 6, "③ polish_title_llm — если is_generic_title (бюджет 10)", "llm"),
        (6, 3, "исправленный заголовок / no-op", "ret"),
        (3, 6, "④ judge_article_keep — keep/drop (бюджет 24)", "llm"),
        (6, 3, "keep=true | keep=false | ошибка API → keep", "ret"),
        (3, 8, "Пишем карточку в data/raw/custom_*.json", "sync"),
        (3, 2, "probe: N статей, статус ready", "ret"),
        (2, 8, "Строка custom_sources + rules_json (crawl_trafilatura)", "sync"),
        (2, 1, "«N статей. Нажмите Обновить данные»", "ret"),
        (0, 1, "«Обновить данные» (отдельный прогон)", "sync"),
        (1, 2, "scrape_all_custom_sources → merge_and_upsert", "sync"),
        (2, 8, "merge → SQLite articles (дедуп по link)", "sync"),
        (2, 1, "Карточки видны в радаре / «Статьи парсера»", "ret"),
    ]

    y = lifeline_top + 28
    row_h = 52
    frag_pad = 10

    def msg_color(kind: str):
        if kind == "llm":
            return LLM_BD
        if kind == "ret":
            return (100, 116, 139)
        if kind == "note":
            return (71, 85, 105)
        return INK

    for idx, (a, b, text, kind) in enumerate(messages, start=1):
        xa, xb = xs[a], xs[b]
        color = msg_color(kind)

        if kind == "note":
            # Fragment note spanning from Pipe to Extr
            x1 = min(xs[3], xs[7]) - 70
            x2 = max(xs[3], xs[7]) + 70
            note_lines = wrap(draw, text, f_msg, x2 - x1 - 24)
            nh = 18 + 20 * len(note_lines)
            rounded(draw, (x1, y - 6, x2, y - 6 + nh), FRAG, FRAG_BD, r=8, width=1)
            ty = y + 4
            for ln in note_lines:
                draw.text((x1 + 12, ty), ln, fill=MUTED, font=f_msg)
                ty += 20
            y += nh + 18
            continue

        if kind == "self":
            # Self-call loop on participant
            x = xa
            loop_r = 28
            draw.arc((x + 4, y - 8, x + 4 + loop_r, y - 8 + 24), 270, 90, fill=color, width=2)
            draw.line((x + 4 + loop_r, y + 4, x + 8, y + 4), fill=color, width=2)
            draw.polygon([(x + 8, y + 4), (x + 18, y), (x + 18, y + 8)], fill=color)
            num = f"{idx}."
            draw.text((x + 36, y - 8), num, fill=MUTED, font=f_num)
            draw.text((x + 36 + text_w(draw, num, f_num) + 6, y - 8), text, fill=color, font=f_msg)
            # thin activation bar
            draw.rectangle((x - 4, y - 10, x + 4, y + 14), fill=(214, 211, 209), outline=LOCAL_BD)
            y += row_h
            continue

        # activation bars
        draw.rectangle((xa - 4, y - 12, xa + 4, y + 12), fill=(226, 232, 240), outline=LOCAL_BD)
        draw.rectangle((xb - 4, y - 12, xb + 4, y + 12), fill=(226, 232, 240), outline=LOCAL_BD)

        # number badge left of message mid
        mid_x = (xa + xb) / 2
        num = f"{idx}"
        nw = text_w(draw, num, f_num) + 10
        badge_x = min(xa, xb) + 12
        if abs(xb - xa) > 180:
            badge_x = int(mid_x - nw / 2)
        rounded(draw, (badge_x, y - 22, badge_x + nw, y - 4), WHITE, color, r=8, width=1)
        draw.text((badge_x + 5, y - 20), num, fill=color, font=f_num)

        # message line slightly below badge
        y_line = y + 4
        if kind == "ret":
            # dashed return
            x_start, x_end = xa, xb
            step = 8 if x_end > x_start else -8
            x = x_start
            while (step > 0 and x < x_end - 12) or (step < 0 and x > x_end + 12):
                draw.line((x, y_line, x + step * 0.6, y_line), fill=color, width=2)
                x += step
            direction = 1 if x_end > x_start else -1
            draw.polygon(
                [(x_end, y_line), (x_end - 10 * direction, y_line - 5), (x_end - 10 * direction, y_line + 5)],
                fill=color,
            )
        else:
            arrow(draw, xa, y_line, xb, y_line, color=color, width=2)

        # label above line, offset to avoid lifelines
        label_max = abs(xb - xa) - 40
        if label_max < 160:
            label_max = 420
        lines = wrap(draw, text, f_msg, max(160, label_max))
        # place label centered between participants, above the line
        total_h = 18 * len(lines)
        lx = int(mid_x)
        # if arrow is short, put label to the right of smaller gap
        if abs(xb - xa) < 160:
            lx = max(xa, xb) + 20
            for i, ln in enumerate(lines):
                draw.text((lx, y_line - total_h + i * 18), ln, fill=color, font=f_msg)
        else:
            for i, ln in enumerate(lines):
                tw = text_w(draw, ln, f_msg)
                draw.text((lx - tw // 2, y_line - total_h - 2 + i * 18), ln, fill=color, font=f_msg)

        # LLM highlight strip under message if llm
        if kind == "llm":
            draw.line((min(xa, xb), y_line + 8, max(xa, xb), y_line + 8), fill=LLM_BD, width=1)

        y += row_h + (8 if len(lines) > 1 else 0)

    # Legend BELOW diagram with clear separator
    legend_y = max(y + 40, lifeline_bot + 30)
    draw.line((64, legend_y, W - 64, legend_y), fill=(231, 229, 228), width=2)
    legend_y += 24
    draw.text((64, legend_y), "Легенда", fill=INK, font=font(24, True))
    legend_y += 44

    items = [
        (LOCAL, LOCAL_BD, "Локальный код", "crawl / fetch / trafilatura / scoring — без модели"),
        (LLM, LLM_BD, "Вызов LLM", "① тема домена  ② kind URL  ③ title  ④ keep/drop"),
        (FRAG, FRAG_BD, "Заметка / ветка", "alt / loop / условие без отдельного сообщения"),
        (WHITE, (100, 116, 139), "Ответ (return)", "пунктирная стрелка назад"),
        (WHITE, INK, "Запрос (sync)", "сплошная стрелка вправо/влево"),
    ]
    col_w = 520
    for i, (fill, bd, name, desc) in enumerate(items):
        cx = 64 + (i % 3) * col_w
        cy = legend_y + (i // 3) * 70
        rounded(draw, (cx, cy, cx + 36, cy + 28), fill, bd, r=8)
        draw.text((cx + 48, cy + 2), name, fill=INK, font=f_leg)
        draw.text((cx + 48, cy + 26), desc, fill=MUTED, font=f_small)

    footer = legend_y + 160
    draw.text(
        (64, footer),
        "Файлы: crawl.py · pipeline.py · article_extract.py · llm_gates.py · fetch.py · browser.py · service.py · engine.py",
        fill=MUTED,
        font=f_small,
    )
    # Crop to content
    final_h = footer + 50
    cropped = img.crop((0, 0, W, final_h))
    save_png(cropped, "parser_sequence_uml.png")
    write_sequence_svg(cropped.size[1])


def write_sequence_svg(approx_h: int) -> None:
    """Companion SVG: same story, scalable."""
    path = OUT / "parser_sequence_uml.svg"
    # Keep SVG as a readable companion referencing structure; main deliverable is PNG.
    # For true vector, embed a simplified but complete sequence as SVG groups.
    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="2800" height="{approx_h}" viewBox="0 0 2800 {approx_h}">
  <rect width="100%" height="100%" fill="#fcfcfb"/>
  <text x="64" y="56" font-family="Segoe UI, Arial" font-size="36" font-weight="700" fill="#1c1917">Универсальный парсер — UML Sequence Diagram</text>
  <text x="64" y="92" font-family="Segoe UI, Arial" font-size="20" fill="#57534e">Растровая версия высокого качества: parser_sequence_uml.png (этот SVG — обложка/ярлык; полная схема в PNG)</text>
  <image href="parser_sequence_uml.png" x="0" y="120" width="2800" height="{max(100, approx_h - 140)}"/>
</svg>
'''
    # Better: don't nest PNG oddly. Just skip SVG wrapper and write a proper standalone SVG via second pass.
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="2800" height="200" viewBox="0 0 2800 200">\n'
        '  <rect width="100%" height="100%" fill="#fcfcfb"/>\n'
        '  <text x="64" y="80" font-family="Segoe UI, Arial" font-size="28" font-weight="700" fill="#1c1917">'
        "См. parser_sequence_uml.png — полная UML sequence diagram</text>\n"
        '  <text x="64" y="120" font-family="Segoe UI, Arial" font-size="18" fill="#57534e">'
        "gartner/custom_sources/diagrams/</text>\n"
        "</svg>\n",
        encoding="utf-8",
    )


def render_architecture() -> None:
    """Не-sequence: полная работа парсера — pipeline flowchart."""
    h = 2200
    img = Image.new("RGB", (W, h), BG)
    draw = ImageDraw.Draw(img)
    f_title = font(36, True)
    f_sub = font(20)
    f_h = font(22, True)
    f_b = font(17, True)
    f_t = font(15)
    f_s = font(14)

    draw.text((64, 36), "Универсальный парсер — полная схема работы", fill=INK, font=f_title)
    draw.text(
        (64, 86),
        "Не sequence: конвейер от URL до articles. Жёлтые узлы — LLM; серые — локальный код; зелёные — результат; красные — отсев.",
        fill=MUTED,
        font=f_sub,
    )

    def box(x, y, w, h, fill, bd, title, lines, title_font=f_b):
        rounded(draw, (x, y, x + w, y + h), fill, bd, r=14)
        draw.text((x + 16, y + 12), title, fill=INK, font=title_font)
        ty = y + 42
        for ln in lines:
            for wrapped in wrap(draw, ln, f_t, w - 32):
                draw.text((x + 16, ty), wrapped, fill=MUTED, font=f_t)
                ty += 20
        return (x + w // 2, y + h)  # bottom center for arrows

    def v_arrow(x, y1, y2):
        arrow(draw, x, y1 + 4, x, y2 - 4, color=LINE, width=2)

    def h_arrow(x1, y, x2):
        arrow(draw, x1 + 4, y, x2 - 4, y, color=LINE, width=2)

    # Row 0: input
    cx = W // 2
    box(cx - 220, 140, 440, 90, WHITE, LOCAL_BD, "Вход", ["Домен / URL, напр. https://www.novatek.ru", "UI «Добавить сайт» или scrape_science_org_news / sample"])

    # Stage headers as swim bands
    stages = [
        (0, "1. Краул", LOCAL, LOCAL_BD),
        (1, "2. Тема домена", LLM, LLM_BD),
        (2, "3. Сбор ссылок", LOCAL, LOCAL_BD),
        (3, "4. Kind URL", LLM, LLM_BD),
        (4, "5. Текст", LOCAL, LOCAL_BD),
        (5, "6. Гейты карточки", LLM, LLM_BD),
        (6, "7. Запись", OK, OK_BD),
    ]

    # Layout as 3 columns of pipeline steps for readability
    # Left column: 1-2, middle 3-4, right 5-7 - actually better as vertical main flow with side rejects

    y = 280
    # Step 1
    b1 = box(
        80,
        y,
        820,
        170,
        LOCAL,
        LOCAL_BD,
        "1. crawl_domain  ·  crawl.py",
        [
            "fetch_html_safe: главная, robots.txt, sitemap, RSS",
            "BFS: ≤45 URL, глубина ≤3, только same_site",
            "scoring.news_score + classify_page → hub / article / rss / other",
            "Профиль: hubs, article_candidates, needs_browser, защита (QRATOR…)",
        ],
    )
    b1r = box(
        980,
        y,
        720,
        170,
        LOCAL,
        LOCAL_BD,
        "Файлы шага 1",
        [
            "crawl.py — обход и классификация страниц",
            "fetch.py — HTTP / TLS / cookie-challenge",
            "scoring.py · rules.py — URL score, same_site",
            "browser.py — Playwright HTML (не VLM), если JS-heavy",
        ],
    )
    y = 500
    v_arrow(80 + 410, 450, y)

    # Step 2 theme
    b2 = box(
        80,
        y,
        820,
        150,
        LOCAL,
        LOCAL_BD,
        "2a. classify_theme (локально)",
        [
            "Ключевые слова нефтегаза по HTML главной",
            "≥3 hits → oilgas · 1–2 → mixed · 0 → other",
            "Токен neft/gaz/oil/… в домене переигрывает отказ",
        ],
    )
    b2l = box(
        980,
        y,
        720,
        150,
        LLM,
        LLM_BD,
        "2b. LLM ① refine_theme_once",
        [
            "Только если hits < 3 · не больше 1 вызова на домен",
            "Ответ: oilgas / mixed / other",
            "other без oil-токена в хосте → отказ всего сайта",
        ],
    )
    y = 720
    v_arrow(490, 650, y)

    # Reject branch
    box(1900, 520, 520, 100, NO, NO_BD, "Отказ источника", ["Тема other → не сохраняем", "Карточки не качаем"])
    # arrow to reject from theme
    draw.line((1500, 575, 1900, 570), fill=NO_BD, width=2)
    draw.polygon([(1900, 570), (1888, 564), (1888, 576)], fill=NO_BD)
    draw.text((1520, 548), "other", fill=NO_BD, font=f_s)

    # Step 3 scrape
    b3 = box(
        80,
        y,
        1620,
        150,
        LOCAL,
        LOCAL_BD,
        "3. scrape_discovered  ·  pipeline.py",
        [
            "Хабы + RSS → ссылки с news_score / looks_like_article_url; пагинация rel=next / «далее» (до 3)",
            "При needs_browser: Playwright дождаться сети, клик «ещё», снять HTML",
            "Лимит карточек: 8 при «Добавить сайт», 40 при scrape_all / еженедельном обновлении",
        ],
    )
    y = 930
    v_arrow(490, 870, y)

    # Step 4 kind
    b4 = box(
        80,
        y,
        820,
        160,
        LOCAL,
        LOCAL_BD,
        "4a. classify_page / resolve_page_kind",
        [
            "Эвристика: article / hub / other",
            "URL с id_4 / ELEMENT_ID / news_id — всегда статья",
            "Не зовём LLM на однозначных адресах",
        ],
    )
    b4l = box(
        980,
        y,
        720,
        160,
        LLM,
        LLM_BD,
        "4b. LLM ② classify_kind_llm",
        [
            "Только is_ambiguous_kind · бюджет 8 / домен",
            "article / hub / junk",
            "hub/junk → не извлекать текст",
        ],
    )
    box(1900, 960, 520, 100, NO, NO_BD, "Skip страницы", ["Лента / junk / other", "trafilatura не вызываем"])
    draw.line((1700, 1010, 1900, 1010), fill=NO_BD, width=2)
    draw.polygon([(1900, 1010), (1888, 1004), (1888, 1016)], fill=NO_BD)

    y = 1160
    v_arrow(490, 1090, y)

    # Step 5 extract
    b5 = box(
        80,
        y,
        1620,
        140,
        LOCAL,
        LOCAL_BD,
        "5. extract_article_page  ·  article_extract.py  (без LLM)",
        [
            "Отсев бинарников (JPEG/PDF/ZIP) → trafilatura.extract (+ meta) → fallback BeautifulSoup",
            "Нужно ≥ ~200 символов текста · polish_title локально · дата из meta / <time> / URL",
        ],
    )
    y = 1360
    v_arrow(490, 1300, y)

    # Step 6 gates
    b6a = box(
        80,
        y,
        820,
        150,
        LLM,
        LLM_BD,
        "6a. LLM ③ polish_title_llm",
        [
            "Только если is_generic_title (chrome меню)",
            "Бюджет 10 / домен · title + превью текста",
        ],
    )
    b6b = box(
        980,
        y,
        720,
        150,
        LLM,
        LLM_BD,
        "6b. LLM ④ judge_article_keep",
        [
            "Главный фильтр качества · бюджет 24",
            "keep=false → не пишем · ошибка API ≠ drop",
        ],
    )
    box(1900, 1380, 520, 100, NO, NO_BD, "Drop карточки", ["«О компании», ПДн,", "каталог, навигация…"])
    draw.line((1700, 1435, 1900, 1430), fill=NO_BD, width=2)
    draw.polygon([(1900, 1430), (1888, 1424), (1888, 1436)], fill=NO_BD)

    y = 1580
    v_arrow(490, 1510, y)

    # Step 7 output
    b7 = box(
        80,
        y,
        820,
        160,
        OK,
        OK_BD,
        "7a. Запись парсера",
        [
            "data/raw/custom_<domain>_<hash>.json + .csv",
            "SQLite custom_sources (rules_json, engine=crawl_trafilatura)",
            "Ещё НЕ articles — до «Обновить данные»",
        ],
    )
    b7b = box(
        980,
        y,
        720,
        160,
        OK,
        OK_BD,
        "7b. После «Обновить данные»",
        [
            "scrape_all_custom_sources → merge_and_upsert",
            "Дедуп по link → SQLite articles",
            "Дальше: другой контур радара (кластеры и т.д.)",
        ],
    )

    # Entry points strip
    y = 1820
    box(
        80,
        y,
        1620,
        120,
        WHITE,
        LOCAL_BD,
        "Точки входа",
        [
            "service.py — POST /api/custom-sources, scrape_all_custom_sources",
            "pipeline.py — discover_source + scrape_discovered · engine.py — ArticleRecord, даты",
            "scripts/scrape_science_org_news.py · docs/parser.md — описание контура",
        ],
    )

    # Legend bottom
    y = 2000
    draw.line((64, y, W - 64, y), fill=(231, 229, 228), width=2)
    y += 24
    draw.text((64, y), "Легенда", fill=INK, font=font(24, True))
    y += 40
    legend = [
        (LOCAL, LOCAL_BD, "Локально"),
        (LLM, LLM_BD, "LLM API"),
        (OK, OK_BD, "Результат"),
        (NO, NO_BD, "Отсев"),
    ]
    x = 64
    for fill, bd, name in legend:
        rounded(draw, (x, y, x + 36, y + 28), fill, bd, r=8)
        draw.text((x + 48, y + 4), name, fill=INK, font=font(17))
        x += 200
    draw.text((x + 20, y + 4), "Скрин/VLM не используются · Playwright только как транспорт HTML", fill=MUTED, font=f_s)

    cropped = img.crop((0, 0, W, 2100))
    save_png(cropped, "parser_architecture_flow.png")

    # Minimal SVG pointer
    (OUT / "parser_architecture_flow.svg").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="2800" height="200" viewBox="0 0 2800 200">\n'
        '  <rect width="100%" height="100%" fill="#fcfcfb"/>\n'
        '  <text x="64" y="80" font-family="Segoe UI, Arial" font-size="28" font-weight="700" fill="#1c1917">'
        "См. parser_architecture_flow.png — полная схема работы парсера</text>\n"
        "</svg>\n",
        encoding="utf-8",
    )


def render_architecture_svg_full() -> None:
    """Standalone detailed SVG architecture (vector, presentation-ready)."""
    # Build a clean vector flowchart - more useful than PNG pointer
    path = OUT / "parser_architecture_flow.svg"
    # We'll replace the stub with a real SVG diagram
    parts: list[str] = []
    parts.append('<?xml version="1.0" encoding="UTF-8"?>')
    parts.append('<svg xmlns="http://www.w3.org/2000/svg" width="2400" height="2800" viewBox="0 0 2400 2800">')
    parts.append('<rect width="100%" height="100%" fill="#fcfcfb"/>')
    parts.append('<style>')
    parts.append('  .t{font-family:Segoe UI,Arial,sans-serif;fill:#1c1917}')
    parts.append('  .m{font-family:Segoe UI,Arial,sans-serif;fill:#57534e}')
    parts.append('  .box{stroke-width:2;rx:14;ry:14}')
    parts.append('</style>')
    parts.append('<text class="t" x="56" y="48" font-size="34" font-weight="700">Универсальный парсер — полная схема работы</text>')
    parts.append('<text class="m" x="56" y="82" font-size="18">gartner/custom_sources · от URL до articles · жёлтый = LLM · серый = локально · зелёный = запись · красный = отсев</text>')

    def rect(x, y, w, h, fill, stroke, title, lines, tid=""):
        parts.append(f'<rect class="box" x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{stroke}"/>')
        parts.append(f'<text class="t" x="{x+18}" y="{y+28}" font-size="17" font-weight="700">{title}</text>')
        yy = y + 52
        for ln in lines:
            parts.append(f'<text class="m" x="{x+18}" y="{yy}" font-size="14">{ln}</text>')
            yy += 20
        return x + w / 2, y + h

    def arrow_v(x, y1, y2):
        parts.append(f'<line x1="{x}" y1="{y1}" x2="{x}" y2="{y2-8}" stroke="#78716c" stroke-width="2"/>')
        parts.append(f'<polygon points="{x},{y2} {x-6},{y2-12} {x+6},{y2-12}" fill="#78716c"/>')

    def arrow_h(x1, y, x2, color="#b91c1c"):
        parts.append(f'<line x1="{x1}" y1="{y}" x2="{x2-8}" y2="{y}" stroke="{color}" stroke-width="2"/>')
        parts.append(f'<polygon points="{x2},{y} {x2-12},{y-6} {x2-12},{y+6}" fill="{color}"/>')

    rect(800, 120, 800, 80, "#fff", "#a8a29e", "Вход: URL домена", ["POST /api/custom-sources · scripts/scrape_science_org_news.py"], "in")
    arrow_v(1200, 200, 250)

    rect(80, 250, 1100, 160, "#f5f5f4", "#a8a29e", "1. crawl_domain (crawl.py) — без LLM на ссылках", [
        "fetch_html_safe: главная, robots.txt, sitemap, RSS",
        "BFS ≤45 URL, глубина ≤3, same_site · news_score + classify_page",
        "Профиль: hubs, article_candidates, needs_browser, защита (QRATOR…)",
        "Сопровождение: fetch.py · scoring.py · rules.py · browser.py (HTML only)",
    ])
    rect(1280, 250, 1040, 160, "#f5f5f4", "#a8a29e", "Артефакт шага 1", [
        "JSON-профиль → custom_sources.rules_json",
        "engine: crawl_trafilatura",
        "Список хабов и кандидатов-статей",
        "Флаг needs_browser для Playwright",
    ])
    arrow_v(630, 410, 470)

    rect(80, 470, 700, 140, "#f5f5f4", "#a8a29e", "2a. classify_theme (локально)", [
        "Словарь нефтегаза по HTML главной",
        "≥3 → oilgas · 1–2 → mixed · 0 → other",
        "Токен в домене (neft/gaz/oil…) спасает отказ",
    ])
    rect(820, 470, 700, 140, "#fff4d6", "#b45309", "2b. LLM ① refine_theme_once", [
        "Только hits &lt; 3 · ≤1 вызов на домен",
        "oilgas / mixed / other",
        "Файл: llm_gates.py / theme.py",
    ])
    rect(1620, 490, 700, 100, "#fef2f2", "#b91c1c", "Отказ источника", [
        "theme=other → сайт не сохраняем",
        "Карточки не качаются",
    ])
    arrow_h(1520, 540, 1620)
    arrow_v(430, 610, 680)

    rect(80, 680, 1440, 130, "#f5f5f4", "#a8a29e", "3. scrape_discovered (pipeline.py)", [
        "Хабы + RSS → ссылки (news_score / looks_like_article_url) · пагинация next/«далее»",
        "needs_browser → Playwright: сеть, «ещё», снять HTML (не VLM)",
        "Лимит: 8 карточек (добавление сайта) / 40 (scrape_all)",
    ])
    arrow_v(430, 810, 880)

    rect(80, 880, 700, 150, "#f5f5f4", "#a8a29e", "4a. classify_page / resolve_page_kind", [
        "Эвристика article / hub / other",
        "id_4 / ELEMENT_ID / news_id → всегда article",
        "Однозначные URL без LLM",
    ])
    rect(820, 880, 700, 150, "#fff4d6", "#b45309", "4b. LLM ② classify_kind_llm", [
        "Только is_ambiguous_kind · бюджет 8",
        "article / hub / junk",
        "hub/junk → skip извлечения",
    ])
    rect(1620, 910, 700, 100, "#fef2f2", "#b91c1c", "Skip страницы", [
        "Лента / junk — trafilatura не зовём",
        "Экономия шума и бюджета",
    ])
    arrow_h(1520, 960, 1620)
    arrow_v(430, 1030, 1100)

    rect(80, 1100, 1440, 120, "#f5f5f4", "#a8a29e", "5. extract_article_page (article_extract.py) — без LLM", [
        "Отсев JPEG/PDF/ZIP → trafilatura (+ meta) → fallback BeautifulSoup",
        "≥ ~200 символов текста · локальный polish_title · дата из meta / &lt;time&gt; / URL",
    ])
    arrow_v(430, 1220, 1290)

    rect(80, 1290, 700, 140, "#fff4d6", "#b45309", "6a. LLM ③ polish_title_llm", [
        "Только is_generic_title",
        "Бюджет 10 / домен",
        "Убрать chrome меню / title сайта",
    ])
    rect(820, 1290, 700, 140, "#fff4d6", "#b45309", "6b. LLM ④ judge_article_keep", [
        "Главный фильтр · бюджет 24",
        "keep=false → не пишем",
        "Ошибка API ≠ автоматический drop",
    ])
    rect(1620, 1310, 700, 100, "#fef2f2", "#b91c1c", "Drop карточки", [
        "About, ПДн, каталог, навигация…",
        "Не попадает в raw/radar",
    ])
    arrow_h(1520, 1360, 1620)
    arrow_v(430, 1430, 1500)

    rect(80, 1500, 700, 150, "#ecfdf5", "#047857", "7a. Запись парсера", [
        "data/raw/custom_*.json + .csv",
        "SQLite custom_sources",
        "Ещё не таблица articles",
    ])
    rect(820, 1500, 700, 150, "#ecfdf5", "#047857", "7b. «Обновить данные»", [
        "scrape_all → merge_and_upsert",
        "Дедуп по link → articles",
        "Дальше — контур радара (кластеры)",
    ])

    # budgets
    rect(80, 1740, 2240, 120, "#fff", "#a8a29e", "Бюджет LLM на домен (LlmBudget)", [
        "① тема: 1 · ② kind: 8 · ③ title: 10 · ④ keep: 24",
        "FORCE_HEURISTIC=1 или нет ключа → все гейты no-op, остаётся краул + trafilatura",
        "Скрин страницы и VLM в контуре не используются",
    ])

    # legend
    parts.append('<line x1="56" y1="1940" x2="2344" y2="1940" stroke="#e7e5e4" stroke-width="2"/>')
    parts.append('<text class="t" x="56" y="1980" font-size="24" font-weight="700">Легенда</text>')
    legend = [
        (56, "#f5f5f4", "#a8a29e", "Локальный код"),
        (420, "#fff4d6", "#b45309", "Вызов LLM"),
        (780, "#ecfdf5", "#047857", "Успешная запись"),
        (1140, "#fef2f2", "#b91c1c", "Отказ / skip / drop"),
    ]
    for x, fill, stroke, label in legend:
        parts.append(f'<rect x="{x}" y="2010" width="40" height="28" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
        parts.append(f'<text class="t" x="{x+56}" y="2030" font-size="16">{label}</text>')

    parts.append('<text class="m" x="56" y="2100" font-size="15">Ключевые файлы: crawl.py · pipeline.py · article_extract.py · llm_gates.py · fetch.py · browser.py · service.py · engine.py · scoring.py · theme.py</text>')
    parts.append('<text class="m" x="56" y="2135" font-size="15">Документация: docs/parser.md</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {path}")


def render_sequence_svg_full() -> None:
    """Vector sequence diagram with generous spacing."""
    path = OUT / "parser_sequence_uml.svg"
    # Canvas tall enough for ~35 messages
    width = 2600
    height = 3400
    parts: list[str] = []
    parts.append('<?xml version="1.0" encoding="UTF-8"?>')
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">')
    parts.append('<rect width="100%" height="100%" fill="#fcfcfb"/>')
    parts.append('<style>')
    parts.append('.t{font-family:Segoe UI,Arial,sans-serif;fill:#1c1917}')
    parts.append('.m{font-family:Segoe UI,Arial,sans-serif;fill:#57534e}')
    parts.append('.msg{font-family:Segoe UI,Arial,sans-serif;fill:#1c1917;font-size:14px}')
    parts.append('.llm{fill:#b45309}')
    parts.append('</style>')
    parts.append('<text class="t" x="48" y="44" font-size="32" font-weight="700">Универсальный парсер — UML Sequence Diagram</text>')
    parts.append('<text class="m" x="48" y="76" font-size="17">Сценарий «Добавить сайт» → crawl_domain → scrape_discovered → LLM-гейты → raw · затем «Обновить данные» → articles</text>')

    actors = [
        "User", "UI", "API\nservice", "pipeline", "crawl", "fetch/\nbrowser", "LLM\nAPI", "extract", "Disk\nraw+DB",
    ]
    n = len(actors)
    left, right = 80, width - 80
    xs = [left + (right - left) * (i + 0.5) / n for i in range(n)]
    head_y = 120
    box_w, box_h = 150, 64
    life_top = head_y + box_h + 20
    life_bot = 2900

    for i, (name, x) in enumerate(zip(actors, xs)):
        fill = "#fff4d6" if "LLM" in name else "#fff"
        stroke = "#b45309" if "LLM" in name else "#a8a29e"
        parts.append(f'<rect x="{x-box_w/2}" y="{head_y}" width="{box_w}" height="{box_h}" rx="12" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
        lines = name.split("\n")
        yy = head_y + (22 if len(lines) == 1 else 18)
        for ln in lines:
            parts.append(f'<text class="t" x="{x}" y="{yy}" font-size="14" font-weight="700" text-anchor="middle">{ln}</text>')
            yy += 18
        parts.append(f'<line x1="{x}" y1="{life_top}" x2="{x}" y2="{life_bot}" stroke="#d6d3d1" stroke-width="1.5" stroke-dasharray="6 6"/>')

    msgs = [
        (0, 1, "URL + «Добавить сайт»", "s"),
        (1, 2, "POST /api/custom-sources {url}", "s"),
        (2, 3, "add_custom_source → discover_source()", "s"),
        (3, 4, "crawl_domain(start_url, llm, budget)", "s"),
        (4, 5, "fetch_html_safe: главная, robots.txt", "s"),
        (5, 4, "HTML / challenge / timeout", "r"),
        (4, 4, "Семена: sitemap, RSS, /news, /press", "self"),
        (4, 4, "BFS ≤45 URL, глубина ≤3, same_site", "self"),
        (4, 4, "news_score + classify_page", "self"),
        (4, 4, "classify_theme (ключевые слова)", "self"),
        (4, 6, "① LLM theme — только hits &lt; 3", "l"),
        (6, 4, "oilgas / mixed / other", "r"),
        (4, 3, "Профиль: hubs, candidates, needs_browser", "r"),
        (3, 3, "alt: theme=other → отказ источника", "n"),
        (3, 5, "scrape_discovered: хабы + RSS → ссылки", "s"),
        (5, 3, "HTML хаба (+ Playwright если нужно)", "r"),
        (3, 3, "loop: кандидат (лимит 8 / 40)", "n"),
        (3, 5, "fetch страницы-кандидата", "s"),
        (5, 3, "HTML", "r"),
        (3, 3, "resolve_page_kind / classify_page", "self"),
        (3, 6, "② LLM kind — только спорный URL (≤8)", "l"),
        (6, 3, "article / hub / junk", "r"),
        (3, 3, "не article → skip extract", "n"),
        (3, 7, "extract_article_page (trafilatura)", "s"),
        (7, 3, "title, text, date", "r"),
        (3, 6, "③ LLM polish_title — если generic (≤10)", "l"),
        (6, 3, "новый title / no-op", "r"),
        (3, 6, "④ LLM judge_article_keep (≤24)", "l"),
        (6, 3, "keep / drop / ошибка→keep", "r"),
        (3, 8, "Пишем data/raw/custom_*.json", "s"),
        (3, 2, "probe N статей, status ready", "r"),
        (2, 8, "custom_sources + rules_json", "s"),
        (2, 1, "«N статей. Нажмите Обновить данные»", "r"),
        (0, 1, "«Обновить данные»", "s"),
        (1, 2, "scrape_all → merge_and_upsert", "s"),
        (2, 8, "merge → SQLite articles", "s"),
        (2, 1, "Карточки в радаре", "r"),
    ]

    y = life_top + 36
    row = 58
    for idx, (a, b, text, kind) in enumerate(msgs, 1):
        xa, xb = xs[a], xs[b]
        if kind == "n":
            x1, x2 = min(xs[3], xs[7]) - 60, max(xs[3], xs[7]) + 60
            parts.append(f'<rect x="{x1}" y="{y-14}" width="{x2-x1}" height="36" rx="8" fill="#f1f5f9" stroke="#94a3b8" stroke-width="1"/>')
            parts.append(f'<text class="m" x="{x1+14}" y="{y+8}" font-size="14">{text}</text>')
            y += 50
            continue
        color = "#b45309" if kind == "l" else ("#64748b" if kind == "r" else "#1c1917")
        dash = ' stroke-dasharray="6 4"' if kind == "r" else ""
        if kind == "self":
            parts.append(f'<path d="M {xa+4} {y} C {xa+40} {y-16}, {xa+40} {y+16}, {xa+4} {y+8}" fill="none" stroke="{color}" stroke-width="2"/>')
            parts.append(f'<polygon points="{xa+4},{y+8} {xa+14},{y+2} {xa+14},{y+14}" fill="{color}"/>')
            parts.append(f'<text class="msg" x="{xa+48}" y="{y+4}" fill="{color}">{idx}. {text}</text>')
            y += row
            continue
        parts.append(f'<line x1="{xa}" y1="{y}" x2="{xb}" y2="{y}" stroke="{color}" stroke-width="2"{dash}/>')
        direction = 1 if xb > xa else -1
        parts.append(f'<polygon points="{xb},{y} {xb-10*direction},{y-5} {xb-10*direction},{y+5}" fill="{color}"/>')
        mid = (xa + xb) / 2
        parts.append(f'<rect x="{mid-14}" y="{y-28}" width="28" height="18" rx="6" fill="#fff" stroke="{color}"/>')
        parts.append(f'<text class="t" x="{mid}" y="{y-15}" font-size="12" font-weight="700" text-anchor="middle" fill="{color}">{idx}</text>')
        parts.append(f'<text class="msg" x="{mid}" y="{y-34}" text-anchor="middle" fill="{color}">{text}</text>')
        y += row

    # Legend below with gap
    ly = max(y + 50, life_bot + 40)
    parts.append(f'<line x1="48" y1="{ly}" x2="{width-48}" y2="{ly}" stroke="#e7e5e4" stroke-width="2"/>')
    parts.append(f'<text class="t" x="48" y="{ly+36}" font-size="22" font-weight="700">Легенда (под схемой, не перекрывает сообщения)</text>')
    items = [
        (48, "#fff", "#1c1917", "Sync-запрос — сплошная стрелка"),
        (520, "#fff", "#64748b", "Return — пунктир"),
        (980, "#fff4d6", "#b45309", "LLM ①②③④ — жёлтый участник / оранжевые стрелки"),
        (1580, "#f1f5f9", "#94a3b8", "Заметка alt/loop"),
    ]
    for x, fill, stroke, label in items:
        parts.append(f'<rect x="{x}" y="{ly+56}" width="36" height="26" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
        parts.append(f'<text class="m" x="{x+48}" y="{ly+74}" font-size="15">{label}</text>')
    parts.append(f'<text class="m" x="48" y="{ly+120}" font-size="14">Файлы: crawl.py · pipeline.py · article_extract.py · llm_gates.py · fetch.py · browser.py · service.py · engine.py</text>')
    parts.append(f'<text class="m" x="48" y="{ly+145}" font-size="14">Документация: docs/parser.md · Бюджет LLM/домен: theme 1 · kind 8 · title 10 · keep 24</text>')
    # Adjust height note - keep viewBox large
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {path} (vector)")


def main():
    render_sequence()
    render_architecture()
    render_architecture_svg_full()
    render_sequence_svg_full()
    print("done", OUT)


if __name__ == "__main__":
    main()
