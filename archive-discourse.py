#!/usr/bin/env python3

import argparse
from datetime import date
from hashlib import md5
import html
import mimetypes
import os
import posixpath
import re
from shutil import rmtree
from time import sleep
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup as bs
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# It's preferable to set credentials via environment variables,
# though you can hardcode them here.
API_KEY = os.environ.get("DISCOURSE_API_KEY", "").strip()
API_USERNAME = os.environ.get("DISCOURSE_API_USERNAME", "").strip()

BASE_URL = os.environ.get("DISCOURSE_BASE_URL", "https://discourse.marksmath.org").rstrip("/")
OUTPUT_PATH = os.path.join(
    os.getcwd(), os.environ.get("DISCOURSE_OUTPUT_DIR", "export")
)
ARCHIVE_BLURB = os.environ.get(
    "DISCOURSE_ARCHIVE_BLURB", f"Archived {date.today():%B}, {date.today():%Y}."
)
MAX_MORE_TOPICS = int(os.environ.get("DISCOURSE_MAX_PAGES", "99"))
REQUEST_DELAY_SECONDS = float(os.environ.get("DISCOURSE_REQUEST_DELAY", "1"))
PROGRESS_EVERY = int(os.environ.get("DISCOURSE_PROGRESS_EVERY", "5"))

if API_USERNAME and not API_KEY:
    raise RuntimeError(
        "Set DISCOURSE_API_KEY when using DISCOURSE_API_USERNAME."
    )

if API_KEY and not API_USERNAME:
    raise RuntimeError(
        "Set DISCOURSE_API_USERNAME when using DISCOURSE_API_KEY."
    )


with open("templates/main.html", "r", encoding="utf-8") as main_file:
    MAIN_TEMPLATE = main_file.read()

with open("templates/topic.html", "r", encoding="utf-8") as topic_file:
    TOPIC_TEMPLATE = topic_file.read()

with open("archived.css", "r", encoding="utf-8") as css_file:
    CSS = css_file.read()


BASE_SCHEME = urlparse(BASE_URL).scheme
IMAGES_DIR = None
ASSET_CACHE = {}
ANONYMIZE_USERS = False
PRESERVED_USERNAMES = set()
USER_ALIASES = {}
ANONYMIZED_AVATAR_FILES = {}

MISSING_IMAGE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180" viewBox="0 0 320 180" role="img" aria-label="Missing image">
  <rect width="320" height="180" fill="#f4f4f4"/>
  <rect x="12" y="12" width="296" height="156" fill="none" stroke="#bbbbbb" stroke-width="2"/>
  <path d="M52 126l46-46 33 33 47-58 90 71" fill="none" stroke="#888888" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="108" cy="62" r="14" fill="#bbbbbb"/>
  <text x="160" y="160" text-anchor="middle" font-family="sans-serif" font-size="16" fill="#666666">Image unavailable</text>
</svg>
"""


def build_session():
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": "ArchiveDiscourse/2 (+https://github.com/mcmcclur/ArchiveDiscourse)"
        }
    )
    if API_KEY:
        session.headers.update(
            {
                "Api-Key": API_KEY,
                "Api-Username": API_USERNAME,
            }
        )
    return session


SESSION = build_session()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Archive a Discourse site into static HTML."
    )
    parser.add_argument(
        "--title",
        dest="archive_title",
        help="Override the displayed title for the archived site.",
    )
    parser.add_argument(
        "--anonymize-users",
        action="store_true",
        help="Replace displayed usernames and @mentions with stable aliases.",
    )
    parser.add_argument(
        "--preserve-user",
        dest="preserved_users",
        action="append",
        default=[],
        help="Username to leave unanonymized. May be repeated or passed as a comma-separated list.",
    )
    return parser.parse_args()


def resolve_url(url):
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        return url
    if parsed.netloc:
        return f"{BASE_SCHEME}:{url}"
    return urljoin(f"{BASE_URL}/", url.lstrip("/"))


def get_response(url):
    response = SESSION.get(resolve_url(url), timeout=60)
    response.raise_for_status()
    return response


def get_json(url):
    return get_response(url).json()


def guess_extension(content_type):
    if not content_type:
        return ""
    content_type = content_type.split(";", 1)[0].strip()
    if content_type == "image/svg+xml":
        return ".svg"
    return mimetypes.guess_extension(content_type) or ""


def sanitize_filename(url, content_type="", prefix="asset"):
    parsed = urlparse(url)
    candidate = unquote(posixpath.basename(parsed.path))
    if candidate:
        candidate = candidate.replace("/", "_")
        if "." in candidate and not candidate.startswith("."):
            return candidate
    extension = guess_extension(content_type)
    digest = md5(url.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}{extension}"


def download_asset(url, prefix="asset"):
    resolved = resolve_url(url)
    if resolved in ASSET_CACHE:
        return ASSET_CACHE[resolved]

    response = get_response(resolved)
    filename = sanitize_filename(
        resolved, response.headers.get("content-type", ""), prefix=prefix
    )
    destination = os.path.join(IMAGES_DIR, filename)

    with open(destination, "wb") as asset_file:
        asset_file.write(response.content)

    ASSET_CACHE[resolved] = filename
    return filename


def write_missing_image():
    with open(
        os.path.join(IMAGES_DIR, "missing_image.svg"), "w", encoding="utf-8"
    ) as image_file:
        image_file.write(MISSING_IMAGE_SVG)


def get_site_metadata():
    fallback_title = urlparse(BASE_URL).hostname or BASE_URL
    site_title = fallback_title
    logo_url = None

    try:
        basic_info = get_json("/site/basic-info.json")
        site_title = basic_info.get("title") or site_title
        logo_url = basic_info.get("logo_url") or basic_info.get("logo_small_url")
    except requests.RequestException:
        pass

    if site_title != fallback_title and logo_url:
        return site_title, logo_url

    try:
        soup = bs(get_response(BASE_URL).content, "html.parser")
        if soup.title and soup.title.text.strip():
            site_title = soup.title.text.strip()
        if not logo_url:
            site_logo = soup.find("img", {"id": "site-logo"})
            if site_logo and site_logo.get("src"):
                logo_url = site_logo["src"]
    except requests.RequestException:
        pass

    return site_title, logo_url


def build_site_branding(site_title, site_logo_filename, topic_page=False):
    if not site_logo_filename:
        return '<span id="site-logo-text">Site Logo</span>'

    prefix = "../../../images/" if topic_page else "images/"
    return (
        f'<img src="{prefix}{site_logo_filename}" height="40" '
        'alt="Site Logo" id="site-logo" />'
    )


def slugify_category(name):
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in name)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "uncategorized"


def build_category_nav(category_names):
    links = ['<a href="#" data-category="all">All</a>']
    for category_name in category_names:
        category_slug = slugify_category(category_name)
        links.append(
            f'<a href="#category={category_slug}" data-category="{category_slug}">'
            f"{html.escape(category_name)}</a>"
        )
    return " - ".join(links)


def fetch_categories():
    category_json = get_json("/categories.json")["category_list"]["categories"]
    return {category["id"]: category["name"] for category in category_json}


def normalize_username(username):
    return (username or "").strip().lower()


def build_preserved_usernames(values):
    preserved = set()
    for value in values:
        for username in value.split(","):
            normalized = normalize_username(username)
            if normalized:
                preserved.add(normalized)
    return preserved


def anonymized_username(username):
    normalized = normalize_username(username)
    if not ANONYMIZE_USERS or not normalized or normalized in PRESERVED_USERNAMES:
        return username
    if normalized not in USER_ALIASES:
        USER_ALIASES[normalized] = f"User {len(USER_ALIASES) + 1:03d}"
    return USER_ALIASES[normalized]


def anonymized_user_index(username):
    alias = anonymized_username(username)
    match = re.fullmatch(r"User (\d{3})", alias or "")
    if not match:
        return None
    return int(match.group(1))


def anonymized_mention_text(text):
    stripped = (text or "").strip()
    prefix = "@" if stripped.startswith("@") else ""
    username = stripped[1:] if prefix else stripped
    alias = anonymized_username(username)
    if not alias:
        return text
    return f"{prefix}{alias}"


def index_to_letters(index):
    if not index or index < 1:
        return "?"
    letters = []
    value = index
    while value > 0:
        value -= 1
        letters.append(chr(ord("A") + (value % 26)))
        value //= 26
    return "".join(reversed(letters))


def avatar_background_color(username):
    normalized = normalize_username(username)
    digest = md5(normalized.encode("utf-8")).hexdigest()
    hue = int(digest[:6], 16) % 360
    saturation = 45 + (int(digest[6:8], 16) % 20)
    lightness = 42 + (int(digest[8:10], 16) % 12)
    return f"hsl({hue} {saturation}% {lightness}%)"


def write_anonymized_avatar(username):
    normalized = normalize_username(username)
    if (
        not ANONYMIZE_USERS
        or not normalized
        or normalized in PRESERVED_USERNAMES
    ):
        return None
    if normalized in ANONYMIZED_AVATAR_FILES:
        return ANONYMIZED_AVATAR_FILES[normalized]

    index = anonymized_user_index(username)
    badge_text = index_to_letters(index)
    background = avatar_background_color(username)
    file_name = f"avatar-anon-{index:03d}.svg"
    svg_markup = f"""<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128" role="img" aria-label="{html.escape(anonymized_username(username))}">
  <rect width="128" height="128" rx="12" fill="{background}"/>
  <text x="64" y="82" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="52" font-weight="700" fill="#ffffff">{html.escape(badge_text)}</text>
</svg>
"""
    with open(os.path.join(IMAGES_DIR, file_name), "w", encoding="utf-8") as avatar_file:
        avatar_file.write(svg_markup)

    ANONYMIZED_AVATAR_FILES[normalized] = file_name
    return file_name


def avatar_file_for_username(username, avatar_url=None):
    anonymized_avatar = write_anonymized_avatar(username)
    if anonymized_avatar:
        return anonymized_avatar

    if not avatar_url:
        return "missing_image.svg"

    try:
        return download_asset(avatar_url, prefix="avatar")
    except requests.RequestException as err:
        print("post_row write avatar", avatar_url, repr(err))
        return "missing_image.svg"


def anonymize_quote_title(title_tag):
    for text_node in list(title_tag.contents):
        if not isinstance(text_node, str):
            continue
        original_text = str(text_node)
        match = re.fullmatch(r"(\s*)([^:\s][^:]*?)(:\s*)", original_text)
        if not match:
            continue
        prefix, username, suffix = match.groups()
        alias = anonymized_username(username)
        text_node.replace_with(f"{prefix}{alias}{suffix}")
        avatar_tag = title_tag.find("img", {"class": "avatar"})
        anonymized_avatar = write_anonymized_avatar(username)
        if avatar_tag and anonymized_avatar:
            avatar_tag["src"] = f"../../../images/{anonymized_avatar}"


def rewrite_post_html(content):
    soup = bs(content, "html.parser")

    for tag in soup.find_all("a", {"class": "mention"}):
        replacement = soup.new_tag("span", attrs={"class": "mention"})
        replacement.string = anonymized_mention_text(tag.get_text())
        tag.replace_with(replacement)

    for tag in soup.find_all("span", {"class": "mention"}):
        tag.string = anonymized_mention_text(tag.get_text())

    for title_tag in soup.select("aside.quote div.title"):
        anonymize_quote_title(title_tag)

    for image_tag in soup.find_all("img"):
        image_url = image_tag.get("src")
        if not image_url:
            continue
        if image_url.startswith("../../../images/") or image_url.startswith("images/"):
            continue
        try:
            file_name = download_asset(image_url, prefix="post-image")
            image_tag["src"] = f"../../../images/{file_name}"
        except requests.RequestException as err:
            print("post_row save image", image_url, repr(err))
            image_tag["src"] = "../../../images/missing_image.svg"

    return "".join(str(node) for node in soup.contents)


def get_like_count(post_json):
    for action in post_json.get("actions_summary", []):
        if action.get("id") == 2:
            return int(action.get("count", 0) or 0)
    return 0


def emoji_for_reaction(reaction_id):
    emoji_map = {
        "+1": "👍",
        "-1": "👎",
        "clap": "👏",
        "confused": "😕",
        "cry": "😢",
        "eyes": "👀",
        "frowning_face": "☹️",
        "heart": "❤️",
        "hugs": "🤗",
        "laughing": "😆",
        "open_mouth": "😮",
        "partying_face": "🥳",
        "rage": "😡",
        "rocket": "🚀",
        "thumbsup": "👍",
    }
    return emoji_map.get(reaction_id)


def render_post_engagement(post_json):
    parts = []

    for reaction in post_json.get("reactions", []):
        reaction_id = reaction.get("id")
        count = int(reaction.get("count", 0) or 0)
        if not reaction_id or count <= 0:
            continue
        emoji = emoji_for_reaction(reaction_id) or f":{reaction_id}:"
        label = html.escape(reaction_id.replace("_", " "))
        parts.append(
            '<span class="engagement-pill reaction-pill" '
            f'title="{label}: {count}">{emoji} {count}</span>'
        )

    if not parts:
        like_count = get_like_count(post_json)
        if like_count > 0:
            parts.append(
                '<span class="engagement-pill like-pill" title="Likes">'
                f"❤️ {like_count}</span>"
            )

    if not parts:
        return ""

    return '          <div class="post_engagement">' + "".join(parts) + "</div>\n"


def post_row(post_json):
    avatar_url = post_json["avatar_template"].replace("{size}", "45")
    avatar_file_name = avatar_file_for_username(post_json["username"], avatar_url)

    content = rewrite_post_html(post_json["cooked"])
    user_name = html.escape(anonymized_username(post_json["username"]))

    post_string = '      <div class="post_container">\n'
    post_string += '        <div class="avatar_container">\n'
    post_string += (
        f'          <img src="../../../images/{avatar_file_name}" class="avatar" />\n'
    )
    post_string += "        </div>\n"
    post_string += '        <div class="post">\n'
    post_string += f'          <div class="user_name">{user_name}</div>\n'
    post_string += '          <div class="post_content">\n'
    post_string += content + "\n"
    post_string += "          </div>\n"
    post_string += render_post_engagement(post_json)
    post_string += "        </div>\n"
    post_string += "      </div>\n\n"
    return post_string


def write_topic(topic_json, site_title, archive_blurb, topic_branding_markup):
    topic_download_url = f"/t/{topic_json['slug']}/{topic_json['id']}.json"
    topic_relative_url = f"t/{topic_json['slug']}/{topic_json['id']}"

    os.makedirs(topic_relative_url, exist_ok=True)

    topic_payload = get_json(topic_download_url)
    posts_json = topic_payload["post_stream"]["posts"]
    posts_stream = topic_payload["post_stream"]["stream"][20:]

    chunk_size = 20
    for index in range(0, len(posts_stream), chunk_size):
        chunk = posts_stream[index : index + chunk_size]
        query = "&".join(f"post_ids[]={post_id}" for post_id in chunk)
        posts_payload = get_json(f"/t/{topic_json['id']}/posts.json?{query}")
        posts_json.extend(posts_payload["post_stream"]["posts"])

    post_list_string = "".join(post_row(post_json) for post_json in posts_json)
    topic_file_string = (
        TOPIC_TEMPLATE.replace("<!-- TOPIC_TITLE -->", topic_json["fancy_title"])
        .replace("<!-- JUST_SITE_TITLE -->", html.escape(site_title))
        .replace("<!-- ARCHIVE_BLURB -->", archive_blurb)
        .replace("<!-- POST_LIST -->", post_list_string)
        .replace("<!-- SITE_BRANDING -->", topic_branding_markup)
    )

    with open(
        os.path.join(topic_relative_url, "index.html"), "w", encoding="utf-8"
    ) as output_file:
        output_file.write(topic_file_string)


def topic_row(topic_json, category_id_to_name):
    topic_url = f"t/{topic_json['slug']}/{topic_json['id']}"
    topic_title_text = topic_json["fancy_title"]
    topic_post_count = topic_json["posts_count"]
    topic_pinned = topic_json.get("pinned_globally", False)
    topic_category = category_id_to_name.get(topic_json.get("category_id"), "")
    topic_category_slug = slugify_category(topic_category) if topic_category else "uncategorized"

    topic_html = (
        f'      <div class="topic-row" data-category="{topic_category_slug}">\n'
    )
    topic_html += '        <span class="topic">'
    if topic_pinned:
        topic_html += '<i class="fa fa-thumb-tack"'
        topic_html += ' title="This was a pinned topic so it appears near the top of the page."></i>'
    topic_html += f'<a href="{topic_url}">{topic_title_text}</a></span>\n'
    topic_html += f'        <span class="category">{html.escape(topic_category)}</span>\n'
    topic_html += f'        <span class="post-count">{topic_post_count}</span>\n'
    topic_html += "      </div>\n\n"
    return topic_html


def main():
    global IMAGES_DIR
    global ANONYMIZE_USERS
    global PRESERVED_USERNAMES
    args = parse_args()
    ANONYMIZE_USERS = args.anonymize_users
    PRESERVED_USERNAMES = build_preserved_usernames(args.preserved_users)

    if os.path.exists(OUTPUT_PATH) and os.path.isdir(OUTPUT_PATH):
        rmtree(OUTPUT_PATH)
    os.mkdir(OUTPUT_PATH)
    os.chdir(OUTPUT_PATH)
    os.mkdir("images")
    IMAGES_DIR = os.path.join(os.getcwd(), "images")
    write_missing_image()

    if not API_KEY:
        print("No DISCOURSE_API_KEY set; fetching only publicly visible content.")

    category_id_to_name = fetch_categories()
    site_title, site_logo_url = get_site_metadata()
    display_title = args.archive_title or site_title
    category_names = sorted(set(category_id_to_name.values()), key=str.lower)

    site_logo_filename = None
    if site_logo_url:
        try:
            site_logo_filename = download_asset(site_logo_url, prefix="site-logo")
        except requests.RequestException as err:
            print("site_logo download error", site_logo_url, repr(err))

    main_branding_markup = build_site_branding(display_title, site_logo_filename)
    topic_branding_markup = build_site_branding(
        display_title, site_logo_filename, topic_page=True
    )

    cnt = 0
    topic_list_string = ""
    downloaded_topics = 0
    response = get_json(f"/latest.json?no_definitions=true&page={cnt}")
    topic_list = response["topic_list"]["topics"]
    print("Initiating downloads...")

    for topic in topic_list:
        try:
            write_topic(topic, site_title, ARCHIVE_BLURB, topic_branding_markup)
            topic_list_string += topic_row(topic, category_id_to_name)
            downloaded_topics += 1
            if PROGRESS_EVERY > 0 and downloaded_topics % PROGRESS_EVERY == 0:
                print(f"Downloaded {downloaded_topics} topics")
        except Exception as err:
            print("write_topic error", topic.get("slug"), repr(err))
        sleep(REQUEST_DELAY_SECONDS)

    while "more_topics_url" in response["topic_list"] and cnt < MAX_MORE_TOPICS:
        print("cnt is", cnt, "\n============")
        cnt += 1
        response = get_json(f"/latest.json?no_definitions=true&page={cnt}")
        topic_list = response["topic_list"]["topics"]

        for topic in topic_list[1:]:
            try:
                topic_list_string += topic_row(topic, category_id_to_name)
                write_topic(topic, site_title, ARCHIVE_BLURB, topic_branding_markup)
                downloaded_topics += 1
                if PROGRESS_EVERY > 0 and downloaded_topics % PROGRESS_EVERY == 0:
                    print(f"Downloaded {downloaded_topics} topics")
            except Exception as err:
                print("write_topic error", topic.get("slug"), repr(err))
            sleep(REQUEST_DELAY_SECONDS)

    file_string = (
        MAIN_TEMPLATE.replace(
            "<!-- TITLE -->", f"<title>{html.escape(display_title)}</title>"
        )
        .replace("<!-- JUST_SITE_TITLE -->", html.escape(display_title))
        .replace("<!-- ARCHIVE_BLURB -->", ARCHIVE_BLURB)
        .replace("<!-- ARCHIVE_TITLE -->", html.escape(display_title))
        .replace("<!-- CATEGORY_NAV -->", build_category_nav(category_names))
        .replace("<!-- TOPIC_LIST -->", topic_list_string)
        .replace("<!-- SITE_BRANDING -->", main_branding_markup)
    )

    with open("index.html", "w", encoding="utf-8") as output_file:
        output_file.write(file_string)

    with open("archived.css", "w", encoding="utf-8") as output_file:
        output_file.write(CSS)

    print(f"Downloaded {downloaded_topics} topics total")


if __name__ == "__main__":
    main()
