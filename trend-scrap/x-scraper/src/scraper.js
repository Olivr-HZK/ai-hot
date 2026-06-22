/**
 * X scraper entrypoint.
 *
 * Fetches X posts from RapidAPI Twttr API, normalizes common fields,
 * saves raw payloads, and writes a cleaned filtered-result.json for
 * downstream Python steps.
 */

const fs = require("fs");
const path = require("path");

const ROOT_DIR = path.resolve(__dirname, "..", "..", "..");
const DEFAULT_CHECKPOINT_ROOT = path.join(ROOT_DIR, "skill_runs", "scrape_checkpoints");

const CONFIG = {
  rapidApiKey: process.env.X_RAPIDAPI_KEY || "",
  rapidApiHost: process.env.X_RAPIDAPI_HOST || "twitter241.p.rapidapi.com",
  baseUrl: "https://twitter241.p.rapidapi.com",
  dataDir: path.join(__dirname, "..", "data"),
  search: {
    endpoint: "/search-v3",
    type: "Latest",
    count: 25,
    pagesPerTerm: 1,
    maxSearchQueries: 20,
    cursor: "",
    searchTerms: [],
  },
  qualityCreators: {
    enabled: true,
    sheetUrl: "https://scnmrtumk0zm.feishu.cn/wiki/HLs9wvAACiq5HzkM7cDcmYkAnwf?sheet=yYzT06",
    maxAccounts: 20,
    postsPerAccount: 20,
    pagesPerAccount: 1,
    reduceQueriesPerHit: 2,
    minSearchQueries: 8,
  },
  filters: {
    maxHoursAgo: 72,
    minViewCount: 0,
    minLikeCount: 0,
    fallbackMinLikeCount: 20,
    fallbackMinRetweetCount: 5,
  },
};

const X_CORE_WORKFLOW_QUERIES = [
  "ChatGPT Seedance iPhone vlog workflow",
  "GPT Images Seedance Suno couple video",
  "GPT Images Seedance prompt workflow",
  "photo to video storyboard prompt",
  "Kavi selfie to video prompt workflow",
  "AI Avatar Jigsaw prompt workflow",
];

const CATEGORY_CANDIDATES_BY_TERM = {
  "ai video": ["ai视频玩法"],
  "ai dance": ["ai视频玩法"],
  "ai effect": ["ai视频玩法", "ai工具滤镜"],
  "ai photo": ["ai图像玩法", "ai工具滤镜"],
  "ai portrait": ["ai图像玩法", "真人图片素材"],
  "kavi": ["ai视频玩法"],
  "selfie video": ["ai视频玩法"],
  "3d figure": ["ai视频玩法"],
  "avatar jigsaw": ["ai图像玩法", "小游戏玩法"],
  "jigsaw puzzle": ["小游戏玩法"],
  "clay avatar": ["ai图像玩法", "小游戏玩法"],
  "ai style": ["ai图像玩法"],
  "portrait photography": ["真人图片素材"],
  "fashion photoshoot": ["真人图片素材"],
  "editorial portrait": ["真人图片素材"],
  "creative portrait": ["真人图片素材"],
  "holiday photoshoot": ["真人图片素材"],
  "style photo": ["真人图片素材"],
};

function safeNumber(value) {
  const num = Number(value);
  return Number.isFinite(num) ? num : 0;
}

function computeHeatScore(item) {
  return (
    safeNumber(item.view_count) +
    safeNumber(item.like_count) * 30 +
    safeNumber(item.reply_count) * 20 +
    safeNumber(item.retweet_count) * 40
  );
}

function formatErrorDetails(error) {
  const parts = [];
  if (error?.message) {
    parts.push(`message=${error.message}`);
  }
  if (error?.status) {
    parts.push(`status=${error.status}`);
  }
  if (error?.statusText) {
    parts.push(`statusText=${error.statusText}`);
  }
  if (error?.cause) {
    if (error.cause.name) {
      parts.push(`causeName=${error.cause.name}`);
    }
    if (error.cause.code) {
      parts.push(`causeCode=${error.cause.code}`);
    }
    if (error.cause.errno) {
      parts.push(`causeErrno=${error.cause.errno}`);
    }
    if (error.cause.syscall) {
      parts.push(`causeSyscall=${error.cause.syscall}`);
    }
    if (error.cause.message) {
      parts.push(`causeMessage=${error.cause.message}`);
    }
  }
  return parts.join(" | ");
}

function ensureDir(dir) {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

function envBool(name, defaultValue = false) {
  const raw = String(process.env[name] || "").trim().toLowerCase();
  if (!raw) return defaultValue;
  if (["1", "true", "yes", "y", "on"].includes(raw)) return true;
  if (["0", "false", "no", "n", "off"].includes(raw)) return false;
  return defaultValue;
}

function resolveRepoPath(raw, fallback) {
  if (!raw) return fallback;
  return path.isAbsolute(raw) ? raw : path.join(ROOT_DIR, raw);
}

function writeJsonAtomic(filepath, payload) {
  fs.mkdirSync(path.dirname(filepath), { recursive: true });
  const tmpPath = path.join(path.dirname(filepath), `.${path.basename(filepath)}.${process.pid}.tmp`);
  fs.writeFileSync(tmpPath, JSON.stringify(payload, null, 2), "utf-8");
  fs.renameSync(tmpPath, filepath);
}

function checkpointDir(platform) {
  return path.join(resolveRepoPath(process.env.SCRAPE_CHECKPOINT_DIR || "", DEFAULT_CHECKPOINT_ROOT), platform);
}

function runIdFromEnv() {
  return process.env.PIPELINE_RUN_ID || new Date().toISOString().replace(/[-:T.]/g, "").slice(0, 14);
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function loadEnvFile() {
  const envPath = path.join(ROOT_DIR, ".env");
  if (!fs.existsSync(envPath)) {
    return;
  }

  const lines = fs.readFileSync(envPath, "utf-8").split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) {
      continue;
    }
    const [key, ...rest] = trimmed.split("=");
    const value = rest.join("=").trim();
    if (!process.env[key.trim()]) {
      process.env[key.trim()] = value;
    }
  }
}

function loadFeedbackRules() {
  const rulesPath = path.join(ROOT_DIR, "references", "tiktok_feedback_optimization_rules.json");
  if (!fs.existsSync(rulesPath)) return {};
  try {
    return JSON.parse(fs.readFileSync(rulesPath, "utf-8"));
  } catch (error) {
    console.warn(`Feedback rules read failed: ${error.message}`);
    return {};
  }
}

function getRuleScrapeConfig(rules) {
  const scrape = rules && typeof rules === "object" ? rules.x_scrape || {} : {};
  const queries = Array.isArray(scrape.search_queries) ? scrape.search_queries.map((query) => String(query || "").trim()).filter(Boolean) : [];
  const resultsPerKeyword = Number.parseInt(scrape.results_per_keyword, 10);
  const maxSearchQueries = Number.parseInt(scrape.max_search_queries, 10);
  const qualityCreators = scrape.quality_creators || {};
  return {
    searchQueries: queries,
    resultsPerKeyword: Number.isFinite(resultsPerKeyword) && resultsPerKeyword > 0 ? resultsPerKeyword : null,
    maxSearchQueries: Number.isFinite(maxSearchQueries) && maxSearchQueries > 0 ? maxSearchQueries : null,
    qualityCreators: {
      enabled:
        typeof qualityCreators.enabled === "boolean"
          ? qualityCreators.enabled
          : scrape.quality_creators_enabled,
      sheetUrl: String(qualityCreators.sheet_url || scrape.quality_creators_sheet_url || "").trim(),
      maxAccounts: positiveNumberOrNull(qualityCreators.max_accounts || scrape.quality_creators_max_accounts),
      postsPerAccount: positiveNumberOrNull(qualityCreators.posts_per_account || scrape.quality_creators_posts_per_account),
      pagesPerAccount: positiveNumberOrNull(qualityCreators.pages_per_account || scrape.quality_creators_pages_per_account),
      reduceQueriesPerHit: positiveNumberOrNull(
        qualityCreators.reduce_queries_per_hit || scrape.quality_creators_reduce_queries_per_hit
      ),
      minSearchQueries: positiveNumberOrNull(qualityCreators.min_search_queries || scrape.quality_creators_min_search_queries),
    },
  };
}

function envNumber(name, fallback) {
  const value = Number(process.env[name]);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

function positiveNumberOrNull(value) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

async function rapidApiRequest(baseUrl, host, apiKey, endpoint, queryParams = {}) {
  const url = new URL(endpoint, baseUrl);
  for (const [key, value] of Object.entries(queryParams)) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    url.searchParams.set(key, String(value));
  }

  const response = await fetch(url.toString(), {
    method: "GET",
    headers: {
      "X-RapidAPI-Key": apiKey,
      "X-RapidAPI-Host": host,
    },
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`RapidAPI request failed (${response.status}): ${body}`);
  }

  return response.json();
}

async function feishuRequest(endpoint, token, options = {}) {
  const response = await fetch(`https://open.feishu.cn${endpoint}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json; charset=utf-8",
      ...(options.headers || {}),
    },
  });

  const text = await response.text();
  let payload = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch (error) {
    throw new Error(`Feishu response was not valid JSON: ${text.slice(0, 200)}`);
  }

  if (!response.ok || safeNumber(payload.code) !== 0) {
    throw new Error(`Feishu request failed (${response.status}): ${text.slice(0, 500)}`);
  }
  return payload;
}

async function getFeishuTenantToken() {
  const appId = String(process.env.FEISHU_APP_ID || "").trim();
  const appSecret = String(process.env.FEISHU_APP_SECRET || "").trim();
  if (!appId || !appSecret) {
    throw new Error("FEISHU_APP_ID/FEISHU_APP_SECRET are required for X quality creator sheet");
  }

  const response = await fetch("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal", {
    method: "POST",
    headers: { "Content-Type": "application/json; charset=utf-8" },
    body: JSON.stringify({ app_id: appId, app_secret: appSecret }),
  });
  const payload = await response.json();
  if (!response.ok || safeNumber(payload.code) !== 0 || !payload.tenant_access_token) {
    throw new Error(`Feishu token request failed: ${JSON.stringify(payload).slice(0, 500)}`);
  }
  return payload.tenant_access_token;
}

function parseFeishuSheetUrl(rawUrl) {
  const raw = String(rawUrl || "").trim();
  if (!raw) return { spreadsheetToken: "", wikiToken: "", sheetId: "" };
  try {
    const url = new URL(raw);
    const sheetId = url.searchParams.get("sheet") || "";
    const wikiMatch = url.pathname.match(/\/wiki\/([^/?#]+)/);
    const sheetMatch = url.pathname.match(/\/sheets\/([^/?#]+)/);
    return {
      spreadsheetToken: sheetMatch ? sheetMatch[1] : "",
      wikiToken: wikiMatch ? wikiMatch[1] : "",
      sheetId,
    };
  } catch (error) {
    return { spreadsheetToken: "", wikiToken: "", sheetId: "" };
  }
}

async function resolveFeishuSpreadsheetToken(sheetUrl, token) {
  const parsed = parseFeishuSheetUrl(sheetUrl);
  if (parsed.spreadsheetToken) {
    return parsed;
  }
  if (!parsed.wikiToken) {
    throw new Error("Invalid Feishu sheet URL");
  }
  const payload = await feishuRequest(`/open-apis/wiki/v2/spaces/get_node?token=${encodeURIComponent(parsed.wikiToken)}`, token);
  const node = payload.data?.node || {};
  const spreadsheetToken = node.obj_token || node.objToken || "";
  if (!spreadsheetToken) {
    throw new Error("Feishu wiki node did not resolve to a sheet token");
  }
  return { ...parsed, spreadsheetToken };
}

function cellToText(value) {
  if (value === undefined || value === null) return "";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.map(cellToText).filter(Boolean).join(" ");
  }
  if (isObject(value)) {
    const candidates = [
      value.text,
      value.link,
      value.url,
      value.value,
      value.name,
      value.en_us,
      value.zh_cn,
    ];
    return candidates.map(cellToText).filter(Boolean).join(" ");
  }
  return "";
}

function extractXUsername(value) {
  const raw = cellToText(value).trim();
  if (!raw) return "";
  const urlMatch = raw.match(/https?:\/\/(?:www\.)?(?:x|twitter)\.com\/([A-Za-z0-9_]{1,15})(?:[/?#\s]|$)/i);
  if (urlMatch) {
    const username = urlMatch[1];
    if (!["home", "search", "hashtag", "intent", "share", "i"].includes(username.toLowerCase())) {
      return username;
    }
  }
  const handleMatch = raw.match(/@([A-Za-z0-9_]{1,15})\b/);
  if (handleMatch) {
    return handleMatch[1];
  }
  if (/^[A-Za-z0-9_]{1,15}$/.test(raw)) {
    return raw;
  }
  return "";
}

async function readQualityCreatorsFromFeishu(sheetUrl, limit) {
  const token = await getFeishuTenantToken();
  const { spreadsheetToken, sheetId } = await resolveFeishuSpreadsheetToken(sheetUrl, token);
  if (!spreadsheetToken || !sheetId) {
    throw new Error("Feishu quality creator sheet URL is missing token or sheet id");
  }

  const range = encodeURIComponent(`${sheetId}!A1:T500`);
  const payload = await feishuRequest(`/open-apis/sheets/v2/spreadsheets/${spreadsheetToken}/values/${range}`, token);
  const rows = payload.data?.valueRange?.values || payload.data?.value_range?.values || [];
  const seen = new Set();
  const creators = [];
  for (const row of rows) {
    const cells = Array.isArray(row) ? row : [row];
    for (const cell of cells) {
      const username = extractXUsername(cell);
      if (!username) continue;
      const key = username.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      creators.push(username);
      break;
    }
    if (creators.length >= limit) {
      break;
    }
  }
  return creators;
}

function unwrapTweet(node) {
  let current = node;

  while (isObject(current)) {
    if (isObject(current.tweet_results) && isObject(current.tweet_results.result)) {
      current = current.tweet_results.result;
      continue;
    }
    if (isObject(current.tweetResult) && isObject(current.tweetResult.result)) {
      current = current.tweetResult.result;
      continue;
    }
    if (
      isObject(current.itemContent) &&
      isObject(current.itemContent.tweet_results) &&
      isObject(current.itemContent.tweet_results.result)
    ) {
      current = current.itemContent.tweet_results.result;
      continue;
    }
    if (current.__typename === "TweetWithVisibilityResults" && isObject(current.tweet)) {
      current = current.tweet;
      continue;
    }
    if (isObject(current.result) && current.result !== current) {
      const inner = current.result;
      if (inner.rest_id || inner.legacy || inner.note_tweet || inner.views || inner.__typename) {
        current = inner;
        continue;
      }
    }
    break;
  }

  return current;
}

function extractText(tweet) {
  return (
    tweet.details?.full_text ||
    tweet.details?.text ||
    tweet.note_tweet?.note_tweet_results?.result?.text ||
    tweet.note_tweet?.note_tweet_results?.result?.richtext ||
    tweet.legacy?.full_text ||
    tweet.full_text ||
    tweet.text ||
    ""
  );
}

function extractAuthor(tweet) {
  const userResult =
    tweet.core?.user_results?.result ||
    tweet.user_results?.result ||
    tweet.author?.result ||
    tweet.author ||
    {};
  const userLegacy = userResult.legacy || userResult;
  const userCore = userResult.core || userLegacy.core || {};

  const username =
    userCore.screen_name ||
    userLegacy.screen_name ||
    userLegacy.username ||
    userLegacy.userName ||
    tweet.userName ||
    tweet.username ||
    "";

  const displayName =
    userCore.name ||
    userLegacy.name ||
    userLegacy.display_name ||
    userLegacy.displayName ||
    tweet.authorName ||
    username;

  return {
    username: String(username || "").trim(),
    display_name: String(displayName || "").trim(),
  };
}

function buildTweetUrl(tweet, author) {
  const directUrl = tweet.url || tweet.tweetUrl || tweet.postUrl || "";
  if (directUrl) {
    return directUrl;
  }

  const tweetId = String(tweet.rest_id || tweet.id_str || tweet.id || tweet.tweetId || "");
  if (author.username && tweetId) {
    return `https://x.com/${author.username}/status/${tweetId}`;
  }
  return "";
}

function extractViewCount(tweet) {
  return safeNumber(
    tweet.views?.count ||
      tweet.ext_views?.count ||
      tweet.legacy?.views?.count ||
      tweet.viewCount ||
      tweet.impressionCount ||
      tweet.views
  );
}

function extractMediaItems(tweet) {
  const mediaSources = [
    tweet.media_entities,
    tweet.legacy?.media_entities,
    tweet.legacy?.extended_entities?.media,
    tweet.extended_entities?.media,
    tweet.legacy?.entities?.media,
    tweet.entities?.media,
  ];

  for (const media of mediaSources) {
    if (Array.isArray(media) && media.length) {
      return media;
    }
  }

  return [];
}

function extractVideoDurationSeconds(tweet) {
  const mediaItems = extractMediaItems(tweet);
  let maxDurationMillis = 0;

  for (const media of mediaItems) {
    if (!isObject(media)) {
      continue;
    }

    const durationMillis = safeNumber(
      media.media_results?.result?.media_info?.duration_millis ||
        media.media_results?.result?.mediaInfo?.durationMillis ||
      media.video_info?.duration_millis ||
        media.videoInfo?.durationMillis ||
        media.duration_millis ||
        media.durationMillis ||
        media.original_info?.duration_millis ||
        media.originalInfo?.durationMillis
    );

    if (durationMillis > maxDurationMillis) {
      maxDurationMillis = durationMillis;
    }
  }

  if (maxDurationMillis <= 0) {
    return null;
  }

  return Math.ceil(maxDurationMillis / 1000);
}

function extractMediaTypes(tweet) {
  const mediaItems = extractMediaItems(tweet);
  const mediaTypes = new Set();

  for (const media of mediaItems) {
    if (!isObject(media)) {
      continue;
    }
    const explicitType = String(media.type || media.media_type || media.mediaType || "").trim().toLowerCase();
    if (explicitType) {
      mediaTypes.add(explicitType);
      continue;
    }

    const typename = String(media.media_results?.result?.media_info?.__typename || "").trim().toLowerCase();
    if (typename.includes("video")) {
      mediaTypes.add("video");
      continue;
    }
    if (typename.includes("gif")) {
      mediaTypes.add("animated_gif");
      continue;
    }
    if (typename.includes("image") || typename.includes("photo")) {
      mediaTypes.add("photo");
    }
  }

  return [...mediaTypes];
}

function extractMediaUrls(tweet) {
  const mediaItems = extractMediaItems(tweet);
  const urls = new Set();

  for (const media of mediaItems) {
    if (!isObject(media)) {
      continue;
    }
    const candidates = [
      media.media_url_https,
      media.media_url,
      media.url,
      media.expanded_url,
      media.preview_image_url,
      media.original_info?.url,
      media.media_results?.result?.media_url_https,
      media.media_results?.result?.mediaUrlHttps,
      media.media_results?.result?.preview_image_url,
      media.media_results?.result?.previewImageUrl,
    ];
    for (const candidate of candidates) {
      const value = String(candidate || "").trim();
      if (value.startsWith("http")) {
        urls.add(value);
      }
    }
    const variants = media.video_info?.variants || media.media_results?.result?.media_info?.variants || [];
    if (Array.isArray(variants)) {
      for (const variant of variants) {
        const value = String(variant?.url || "").trim();
        if (value.startsWith("http")) {
          urls.add(value);
        }
      }
    }
  }

  return [...urls];
}

function parseCreatedAt(value) {
  if (value === undefined || value === null || value === "") {
    return null;
  }

  if (typeof value === "number" && Number.isFinite(value)) {
    const timestamp = value > 1e12 ? value : value * 1000;
    const date = new Date(timestamp);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  if (typeof value === "string") {
    const raw = value.trim();
    if (!raw) {
      return null;
    }

    if (/^\d+$/.test(raw)) {
      const numericValue = Number(raw);
      const timestamp = numericValue > 1e12 ? numericValue : numericValue * 1000;
      const date = new Date(timestamp);
      return Number.isNaN(date.getTime()) ? null : date;
    }

    const date = new Date(raw);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  return null;
}

function parseTargetDate(value) {
  const raw = String(value || "").trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
    return "";
  }
  return raw;
}

function nextIsoDate(isoDate) {
  const date = new Date(`${isoDate}T00:00:00.000Z`);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}

function dateInShanghai(date) {
  try {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(date);
  } catch (error) {
    return date.toISOString().slice(0, 10);
  }
}

function stripDateOperators(term) {
  return String(term || "")
    .replace(/\s+(since|until):\d{4}-\d{2}-\d{2}\b/g, "")
    .trim()
    .toLowerCase();
}

function looksLikeTweet(node) {
  const tweet = unwrapTweet(node);
  if (!isObject(tweet)) {
    return false;
  }

  const tweetId = tweet.rest_id || tweet.id_str || tweet.id || tweet.tweetId;
  const hasTweetContent = Boolean(extractText(tweet) || tweet.legacy || tweet.note_tweet || tweet.views || tweet.core);
  const typename = String(tweet.__typename || "");
  return Boolean(tweetId && (hasTweetContent || typename.includes("Tweet")));
}

function normalizeTweet(node, searchTerm) {
  const tweet = unwrapTweet(node);
  const author = extractAuthor(tweet);
  const legacy = tweet.legacy || {};
  const text = String(extractText(tweet) || "").trim();
  const id = String(tweet.rest_id || tweet.id_str || tweet.id || tweet.tweetId || "").trim();
  const url = buildTweetUrl(tweet, author);
  const videoDurationSeconds = extractVideoDurationSeconds(tweet);
  const mediaTypes = extractMediaTypes(tweet);
  const mediaUrls = extractMediaUrls(tweet);
  const hasVisualMedia = mediaTypes.length > 0;

  return {
    id,
    url,
    text,
    author,
    created_at:
      legacy.created_at ||
      tweet.created_at ||
      tweet.createdAt ||
      tweet.details?.created_at ||
      tweet.details?.created_at_ms ||
      "",
    like_count: safeNumber(
      tweet.counts?.favorite_count || legacy.favorite_count || tweet.favoriteCount || tweet.likeCount || tweet.likes
    ),
    view_count: extractViewCount(tweet),
    reply_count: safeNumber(tweet.counts?.reply_count || legacy.reply_count || tweet.replyCount || tweet.replies),
    retweet_count: safeNumber(
      tweet.counts?.retweet_count || legacy.retweet_count || tweet.retweetCount || tweet.retweets
    ),
    video_duration_seconds: videoDurationSeconds,
    media_types: mediaTypes,
    media_urls: mediaUrls,
    media_count: mediaTypes.length,
    has_visual_media: hasVisualMedia,
    search_term: searchTerm,
    raw_source: {
      lang: legacy.lang || tweet.lang || tweet.language || "",
      media_count: mediaTypes.length,
      media_types: mediaTypes,
      media_urls: mediaUrls,
      has_visual_media: hasVisualMedia,
      video_duration_seconds: videoDurationSeconds,
    },
  };
}

function collectTweets(node, searchTerm, seen, results) {
  if (Array.isArray(node)) {
    for (const item of node) {
      collectTweets(item, searchTerm, seen, results);
    }
    return;
  }

  if (!isObject(node)) {
    return;
  }

  if (looksLikeTweet(node)) {
    const normalized = normalizeTweet(node, searchTerm);
    if (normalized.id && !seen.has(normalized.id)) {
      seen.add(normalized.id);
      results.push(normalized);
    }
  }

  for (const value of Object.values(node)) {
    collectTweets(value, searchTerm, seen, results);
  }
}

function extractTweetsFromPayload(payload, searchTerm) {
  const results = [];
  const seen = new Set();
  collectTweets(payload, searchTerm, seen, results);
  return results;
}

function findNextCursor(node) {
  if (Array.isArray(node)) {
    for (const item of node) {
      const cursor = findNextCursor(item);
      if (cursor) {
        return cursor;
      }
    }
    return "";
  }

  if (!isObject(node)) {
    return "";
  }

  if (
    typeof node.value === "string" &&
    typeof (node.cursorType || node.cursor_type) === "string" &&
    String(node.cursorType || node.cursor_type).toLowerCase() === "bottom"
  ) {
    return node.value;
  }

  for (const value of Object.values(node)) {
    const cursor = findNextCursor(value);
    if (cursor) {
      return cursor;
    }
  }

  return "";
}

function normalizeAcceptanceText(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  if (raw === "1" || raw.includes("1星")) return "否决";
  if (raw === "2" || raw.includes("2星")) return "中";
  if (raw === "3" || raw.includes("3星")) return "高";
  if (raw.includes("高")) return "高";
  if (raw.includes("中")) return "中";
  if (raw.includes("低")) return "否决";
  if (raw.includes("无") || raw.includes("否决") || raw.toLowerCase().includes("reject")) return "否决";
  return raw;
}

function queryTokens(query) {
  const stopWords = new Set([
    "ai",
    "photo",
    "video",
    "prompt",
    "workflow",
    "portrait",
    "photography",
    "image",
    "real",
    "person",
    "creative",
  ]);
  return stripDateOperators(query)
    .split(/[^a-z0-9]+/i)
    .map((token) => token.trim().toLowerCase())
    .filter((token) => token.length >= 4 && !stopWords.has(token));
}

function feedbackRowMatchesQuery(row, query) {
  const cleanQuery = stripDateOperators(query);
  const directFields = [
    row.sourceQuery,
    row.searchQuery,
    row.source_query,
    row.search_query,
    row.matched_search_terms,
    row.matchedSearchTerms,
  ];
  for (const field of directFields) {
    const text = Array.isArray(field) ? field.join(" ") : String(field || "");
    if (text.toLowerCase().includes(cleanQuery)) {
      return true;
    }
  }

  const introText = [
    row.hotspotIntro,
    row.hotspot_intro,
    row.intro,
    row.title,
    row.description,
    row.material_reason,
    row.materialReason,
  ]
    .map((field) => String(field || "").toLowerCase())
    .join(" ");
  if (!introText) {
    return false;
  }
  if (introText.includes(cleanQuery)) {
    return true;
  }
  const tokens = queryTokens(query);
  if (!tokens.length) {
    return false;
  }
  const hitCount = tokens.filter((token) => introText.includes(token)).length;
  return hitCount >= Math.min(2, tokens.length);
}

function loadFeedbackRowsForKeywordScoring() {
  const feedbackDir = path.join(ROOT_DIR, "skill_runs", "feedback");
  if (!fs.existsSync(feedbackDir)) {
    return [];
  }
  const files = fs
    .readdirSync(feedbackDir)
    .filter((name) => name.endsWith("_recent_feedback.json"))
    .sort()
    .reverse()
    .slice(0, 14);
  const rows = [];
  for (const file of files) {
    const filepath = path.join(feedbackDir, file);
    try {
      const parsed = JSON.parse(fs.readFileSync(filepath, "utf-8"));
      if (Array.isArray(parsed)) {
        for (const row of parsed) {
          rows.push(row);
        }
      }
    } catch (error) {
      console.warn(`Feedback cache read failed for ${file}: ${error.message}`);
    }
  }
  return rows;
}

function keywordFeedbackScores(queries) {
  const rows = loadFeedbackRowsForKeywordScoring();
  const scores = new Map();
  for (const query of queries) {
    scores.set(stripDateOperators(query), { negative: 0, positive: 0 });
  }
  for (const row of rows) {
    const platform = String(row.platform || row.平台 || "").toLowerCase();
    if (platform && !["x", "twitter"].some((name) => platform.includes(name))) {
      continue;
    }
    const material = normalizeAcceptanceText(row.material_acceptance || row.materialAcceptance || "");
    const isNegative = material === "否决";
    const isPositive = material === "高";
    if (!isNegative && !isPositive) {
      continue;
    }
    for (const query of queries) {
      if (!feedbackRowMatchesQuery(row, query)) {
        continue;
      }
      const key = stripDateOperators(query);
      const score = scores.get(key) || { negative: 0, positive: 0 };
      if (isNegative) score.negative += 1;
      if (isPositive) score.positive += 1;
      scores.set(key, score);
    }
  }
  return scores;
}

function rankSearchQueriesForReduction(queries) {
  const feedbackScores = keywordFeedbackScores(queries);
  const coreSet = new Set(X_CORE_WORKFLOW_QUERIES.map((query) => query.toLowerCase()));
  return queries
    .map((query, index) => {
      const clean = stripDateOperators(query);
      const score = feedbackScores.get(clean) || { negative: 0, positive: 0 };
      return {
        query,
        index,
        clean,
        core: coreSet.has(clean),
        negative: score.negative,
        positive: score.positive,
      };
    })
    .sort((left, right) => {
      if (left.core !== right.core) return left.core ? -1 : 1;
      if (left.negative !== right.negative) return left.negative - right.negative;
      if (left.positive !== right.positive) return right.positive - left.positive;
      return left.index - right.index;
    });
}

function selectSearchQueriesAfterCreatorHits(queries, creatorHitCount, qualityConfig) {
  const beforeCount = queries.length;
  const minSearchQueries = Math.max(1, safeNumber(qualityConfig.minSearchQueries || CONFIG.qualityCreators.minSearchQueries));
  const reducePerHit = Math.max(0, safeNumber(qualityConfig.reduceQueriesPerHit || CONFIG.qualityCreators.reduceQueriesPerHit));
  const targetCount = Math.min(beforeCount, Math.max(minSearchQueries, beforeCount - creatorHitCount * reducePerHit));
  if (targetCount >= beforeCount) {
    return {
      selectedQueries: queries,
      droppedSearchQueries: [],
      dropReasons: {},
      beforeCount,
      afterCount: beforeCount,
    };
  }

  const ranked = rankSearchQueriesForReduction(queries);
  const selectedSet = new Set(ranked.slice(0, targetCount).map((item) => item.index));
  const selectedQueries = queries.filter((_, index) => selectedSet.has(index));
  const dropped = ranked.slice(targetCount);
  const dropReasons = {};
  for (const item of dropped) {
    dropReasons[item.query] =
      item.negative > 0
        ? `historical_negative_feedback=${item.negative}, historical_positive_feedback=${item.positive}`
        : "query_reduction_no_recent_positive_evidence";
  }
  return {
    selectedQueries,
    droppedSearchQueries: dropped.map((item) => item.query),
    dropReasons,
    beforeCount,
    afterCount: selectedQueries.length,
  };
}

function findMatchingUserRestId(node, username) {
  if (!isObject(node) && !Array.isArray(node)) {
    return "";
  }
  const expected = String(username || "").toLowerCase();
  if (Array.isArray(node)) {
    for (const item of node) {
      const found = findMatchingUserRestId(item, username);
      if (found) return found;
    }
    return "";
  }
  const legacy = node.legacy || node.core || node;
  const screenName = String(legacy.screen_name || legacy.username || legacy.userName || "").toLowerCase();
  const id = String(node.rest_id || node.id_str || node.id || legacy.rest_id || legacy.id_str || legacy.id || "").trim();
  if (id && (!expected || screenName === expected)) {
    return id;
  }
  for (const value of Object.values(node)) {
    const found = findMatchingUserRestId(value, username);
    if (found) return found;
  }
  return "";
}

function findFirstUserRestId(node) {
  if (!isObject(node) && !Array.isArray(node)) {
    return "";
  }
  if (Array.isArray(node)) {
    for (const item of node) {
      const found = findFirstUserRestId(item);
      if (found) return found;
    }
    return "";
  }
  const legacy = node.legacy || node.core || node;
  const id = String(node.rest_id || node.id_str || legacy.rest_id || legacy.id_str || "").trim();
  if (/^\d{5,}$/.test(id)) {
    return id;
  }
  for (const value of Object.values(node)) {
    const found = findFirstUserRestId(value);
    if (found) return found;
  }
  return "";
}

function findUserRestId(node, username) {
  return findMatchingUserRestId(node, username) || findFirstUserRestId(node);
}

class XScraper {
  constructor(config = {}) {
    this.config = {
      ...CONFIG,
      ...config,
      search: { ...CONFIG.search, ...(config.search || {}) },
      qualityCreators: { ...CONFIG.qualityCreators, ...(config.qualityCreators || {}) },
      filters: { ...CONFIG.filters, ...(config.filters || {}) },
    };
    this.rawData = [];
    this.filteredData = [];
    this.runId = config.runId || runIdFromEnv();
    this.completedTerms = [];
    this.failedTerms = [];
    this.qualityCreatorStats = {
      qualityCreatorCount: 0,
      qualityCreatorHitCount: 0,
      searchQueryCountBeforeReduction: 0,
      searchQueryCountAfterReduction: 0,
      droppedSearchQueries: [],
      dropReasons: {},
    };
    this.partialContinue = config.partialContinue !== undefined ? Boolean(config.partialContinue) : envBool("SCRAPE_PARTIAL_CONTINUE", true);
    ensureDir(this.config.dataDir);
    ensureDir(path.join(this.config.dataDir, "raw"));
  }

  initClient() {
    if (!this.config.rapidApiKey) {
      throw new Error("RAPIDAPI_KEY is required");
    }
  }

  resolveSearchTerms(searchConfig = {}) {
    const searchTerms = searchConfig.searchTerms || this.config.search.searchTerms || [];
    const seen = new Set();
    const normalized = [];
    for (const term of searchTerms) {
      const value = String(term || "").trim();
      const key = value.toLowerCase();
      if (!value || seen.has(key)) {
        continue;
      }
      seen.add(key);
      normalized.push(value);
    }
    const maxSearchQueries = Math.min(20, Math.max(1, safeNumber(searchConfig.maxSearchQueries || this.config.search.maxSearchQueries || 20)));
    if (normalized.length > maxSearchQueries) {
      console.warn(`X search terms capped at ${maxSearchQueries}; ${normalized.length - maxSearchQueries} extra terms were skipped.`);
      return normalized.slice(0, maxSearchQueries);
    }
    return normalized;
  }

  getCandidateCategoriesForTerm(term) {
    return [...(CATEGORY_CANDIDATES_BY_TERM[stripDateOperators(term)] || [])];
  }

  buildRankedTweetForTerm(tweet, term, captureTier) {
    const candidateCategories = this.getCandidateCategoriesForTerm(term);
    return {
      ...tweet,
      capture_tier: captureTier,
      capture_source: tweet.capture_source || "search",
      capture_sources: [...new Set([...(tweet.capture_sources || []), tweet.capture_source || "search"])],
      candidate_categories: candidateCategories,
      matched_search_terms: [term],
      matched_quality_creator: tweet.matched_quality_creator || "",
    };
  }

  buildQualityCreatorTweet(tweet, username) {
    return {
      ...tweet,
      search_term: `quality_creator:${username}`,
      capture_tier: "strict",
      capture_source: "quality_creator",
      capture_sources: ["quality_creator"],
      matched_quality_creator: username,
      matched_quality_creators: [username],
      matched_search_terms: [],
      candidate_categories: [],
    };
  }

  async fetchSearchPage(term, cursor = "") {
    const queryParams = {
      query: term,
      type: this.config.search.type,
      count: this.config.search.count,
      cursor: cursor || this.config.search.cursor,
    };

    return rapidApiRequest(
      this.config.baseUrl,
      this.config.rapidApiHost,
      this.config.rapidApiKey,
      this.config.search.endpoint,
      queryParams
    );
  }

  async fetchUserRestId(username) {
    const payload = await rapidApiRequest(
      this.config.baseUrl,
      this.config.rapidApiHost,
      this.config.rapidApiKey,
      "/user",
      { username }
    );
    return findUserRestId(payload, username);
  }

  async fetchUserTweetsPage(userId, cursor = "", count = 20) {
    return rapidApiRequest(
      this.config.baseUrl,
      this.config.rapidApiHost,
      this.config.rapidApiKey,
      "/user-tweets",
      {
        user: userId,
        count,
        cursor,
      }
    );
  }

  async fetchQualityCreatorSearchPage(username, cursor = "") {
    return this.fetchSearchPage(`from:${username}`, cursor);
  }

  appendQualityCreatorPage({
    payload,
    username,
    pageIndex,
    cursor,
    seen,
    creatorSeen,
    creatorTweets,
    sourceMethod,
    userId = "",
  }) {
    const tweets = extractTweetsFromPayload(payload, `quality_creator:${username}`);
    const pageFilteredTweets = [];
    this.rawData.push({
      capture_source: "quality_creator",
      quality_creator: username,
      quality_creator_method: sourceMethod,
      user_id: userId,
      page: pageIndex + 1,
      cursor: cursor || "",
      fetched_at: new Date().toISOString(),
      tweets,
    });

    for (const tweet of tweets) {
      if (!tweet.id || creatorSeen.has(tweet.id)) {
        continue;
      }
      creatorSeen.add(tweet.id);
      const globalDuplicate = seen.has(tweet.id);
      if (!globalDuplicate) seen.add(tweet.id);
      if (!this.filterItem(tweet)) {
        continue;
      }
      if (globalDuplicate) {
        continue;
      }
      const rankedTweet = this.buildQualityCreatorTweet(tweet, username);
      rankedTweet.quality_creator_method = sourceMethod;
      pageFilteredTweets.push(rankedTweet);
      creatorTweets.push(rankedTweet);
    }

    this.rawData[this.rawData.length - 1].filtered_tweet_ids = pageFilteredTweets.map((tweet) => tweet.id);
    this.rawData[this.rawData.length - 1].filtered_count = pageFilteredTweets.length;
    this.qualityCreatorStats.qualityCreatorHitCount += pageFilteredTweets.length;
    this.saveCheckpoint("partial", { ...this.qualityCreatorStats });
    return {
      filteredCount: pageFilteredTweets.length,
      nextCursor: findNextCursor(payload),
    };
  }

  async fetchQualityCreatorViaSearch(username, seen, reason) {
    const config = this.config.qualityCreators || {};
    const pagesPerAccount = Math.max(1, safeNumber(config.pagesPerAccount || 1));
    const creatorTweets = [];
    const creatorSeen = new Set();
    let cursor = "";
    console.warn(`  -> falling back to from:${username} search (${reason})`);
    for (let pageIndex = 0; pageIndex < pagesPerAccount; pageIndex += 1) {
      let payload;
      try {
        payload = await this.fetchQualityCreatorSearchPage(username, cursor);
      } catch (error) {
        this.markFailedTerm(`quality_creator:${username}:search_fallback`, pageIndex + 1, error);
        console.warn(`  -> search fallback failed for @${username}: ${formatErrorDetails(error) || error.message}`);
        this.saveCheckpoint("partial", { ...this.qualityCreatorStats });
        break;
      }
      const result = this.appendQualityCreatorPage({
        payload,
        username,
        pageIndex,
        cursor,
        seen,
        creatorSeen,
        creatorTweets,
        sourceMethod: "search_from",
      });
      this.markCompletedTerm(`quality_creator:${username}:search_fallback`, pageIndex + 1);
      cursor = result.nextCursor;
      if (!cursor) {
        break;
      }
    }
    if (!creatorTweets.length) {
      return null;
    }
    return {
      capture_source: "quality_creator",
      quality_creator: username,
      quality_creator_method: "search_from",
      filtered_count: creatorTweets.length,
      tweets: creatorTweets,
    };
  }

  markCompletedTerm(term, page) {
    const value = `${term}#${page}`;
    if (!this.completedTerms.includes(value)) this.completedTerms.push(value);
  }

  markFailedTerm(term, page, error) {
    this.failedTerms.push({
      term,
      page,
      message: formatErrorDetails(error) || String(error),
      at: new Date().toISOString(),
    });
  }

  async loadQualityCreators() {
    const config = this.config.qualityCreators || {};
    if (!config.enabled) {
      return [];
    }
    const sheetUrl = String(config.sheetUrl || "").trim();
    if (!sheetUrl) {
      console.warn("X quality creators enabled but sheet URL is empty; falling back to search-only mode.");
      return [];
    }
    const limit = Math.max(1, safeNumber(config.maxAccounts || 20));
    try {
      const creators = await readQualityCreatorsFromFeishu(sheetUrl, limit);
      this.qualityCreatorStats.qualityCreatorCount = creators.length;
      if (!creators.length) {
        console.warn("X quality creator sheet did not return any X accounts; falling back to full keyword search.");
      } else {
        console.log(`Loaded ${creators.length} X quality creator accounts from Feishu.`);
      }
      return creators;
    } catch (error) {
      console.warn(`X quality creator sheet read failed: ${formatErrorDetails(error) || error.message}`);
      return [];
    }
  }

  async fetchQualityCreatorTweets(creators, seen) {
    const config = this.config.qualityCreators || {};
    const pagesPerAccount = Math.max(1, safeNumber(config.pagesPerAccount || 1));
    const postsPerAccount = Math.max(1, safeNumber(config.postsPerAccount || 20));
    const creatorBuckets = [];
    if (!creators.length) {
      return creatorBuckets;
    }

    console.log(`Fetching recent X posts from ${creators.length} quality creators...`);
    for (const [index, username] of creators.entries()) {
      console.log(`[creator ${index + 1}/${creators.length}] @${username}`);
      let userId = "";
      try {
        userId = await this.fetchUserRestId(username);
      } catch (error) {
        this.markFailedTerm(`quality_creator:${username}`, "profile", error);
        console.warn(`  -> profile fetch failed for @${username}: ${formatErrorDetails(error) || error.message}`);
        this.saveCheckpoint("partial", { ...this.qualityCreatorStats });
        const fallbackBucket = await this.fetchQualityCreatorViaSearch(username, seen, "profile fetch failed");
        if (fallbackBucket) {
          creatorBuckets.push(fallbackBucket);
          console.log(`  -> kept ${fallbackBucket.filtered_count} filtered creator posts for @${username} via search fallback`);
        }
        continue;
      }
      if (!userId) {
        this.markFailedTerm(`quality_creator:${username}`, "profile", new Error("rest_id not found"));
        console.warn(`  -> no rest_id found for @${username}`);
        const fallbackBucket = await this.fetchQualityCreatorViaSearch(username, seen, "rest_id not found");
        if (fallbackBucket) {
          creatorBuckets.push(fallbackBucket);
          console.log(`  -> kept ${fallbackBucket.filtered_count} filtered creator posts for @${username} via search fallback`);
        }
        continue;
      }

      let cursor = "";
      const creatorTweets = [];
      const creatorSeen = new Set();
      for (let pageIndex = 0; pageIndex < pagesPerAccount; pageIndex += 1) {
        let payload;
        try {
          payload = await this.fetchUserTweetsPage(userId, cursor, postsPerAccount);
        } catch (error) {
          this.markFailedTerm(`quality_creator:${username}`, pageIndex + 1, error);
          console.warn(`  -> tweets fetch failed for @${username}: ${formatErrorDetails(error) || error.message}`);
          this.saveCheckpoint("partial", { ...this.qualityCreatorStats });
          break;
        }

        const result = this.appendQualityCreatorPage({
          payload,
          username,
          pageIndex,
          cursor,
          seen,
          creatorSeen,
          creatorTweets,
          sourceMethod: "user_tweets",
          userId,
        });
        this.markCompletedTerm(`quality_creator:${username}`, pageIndex + 1);
        cursor = result.nextCursor;
        if (!cursor) {
          break;
        }
      }

      if (creatorTweets.length) {
        creatorBuckets.push({
          capture_source: "quality_creator",
          quality_creator: username,
          filtered_count: creatorTweets.length,
          tweets: creatorTweets,
        });
        console.log(`  -> kept ${creatorTweets.length} filtered creator posts for @${username}`);
      }
    }

    return creatorBuckets;
  }

  saveCheckpoint(status, extra = {}) {
    const dir = checkpointDir("x");
    const rawPath = path.join(dir, "latest_raw.json");
    const archivePath = path.join(dir, "runs", `${this.runId}_raw.json`);
    const statusPath = path.join(dir, "latest_status.json");
    writeJsonAtomic(rawPath, this.rawData);
    writeJsonAtomic(archivePath, this.rawData);
    writeJsonAtomic(statusPath, {
      platform: "x",
      runId: this.runId,
      status,
      updatedAt: new Date().toISOString(),
      itemCount: this.rawData.length,
      filteredItemCount: this.filteredData.length,
      checkpointPath: rawPath,
      archivePath,
      completed: this.completedTerms,
      failed: this.failedTerms,
      error: extra.error || "",
      ...this.qualityCreatorStats,
      ...extra,
    });
  }

  finalizeScrape(terms, termBuckets, status, extra = {}) {
    this.filteredData = [];
    const filteredMap = new Map();
    for (const bucket of termBuckets) {
      for (const tweet of bucket.tweets) {
        if (!tweet.id) {
          continue;
        }

        const existing = filteredMap.get(tweet.id);
        if (!existing) {
          filteredMap.set(tweet.id, { ...tweet });
          continue;
        }

        const mergedCategories = new Set([...(existing.candidate_categories || []), ...(tweet.candidate_categories || [])]);
        const mergedTerms = new Set([...(existing.matched_search_terms || []), ...(tweet.matched_search_terms || [])]);
        const mergedSources = new Set([...(existing.capture_sources || []), ...(tweet.capture_sources || [])]);
        if (existing.capture_source) mergedSources.add(existing.capture_source);
        if (tweet.capture_source) mergedSources.add(tweet.capture_source);
        const mergedCreators = new Set([...(existing.matched_quality_creators || []), ...(tweet.matched_quality_creators || [])]);
        if (existing.matched_quality_creator) mergedCreators.add(existing.matched_quality_creator);
        if (tweet.matched_quality_creator) mergedCreators.add(tweet.matched_quality_creator);

        existing.candidate_categories = [...mergedCategories];
        existing.matched_search_terms = [...mergedTerms];
        existing.capture_sources = [...mergedSources];
        if (mergedSources.has("quality_creator")) {
          existing.capture_source = "quality_creator";
        } else if (mergedSources.has("search")) {
          existing.capture_source = "search";
        }
        existing.matched_quality_creators = [...mergedCreators];
        existing.matched_quality_creator = existing.matched_quality_creators[0] || "";
        if (existing.capture_tier !== "strict" && tweet.capture_tier === "strict") {
          existing.capture_tier = "strict";
          existing.search_term = tweet.search_term;
        }
      }
    }
    this.filteredData = [...filteredMap.values()];
    this.saveRawData(terms);
    this.saveFilteredData();
    this.saveCheckpoint(status, { ...extra, filteredItemCount: this.filteredData.length });

    return {
      rawCount: this.rawData.reduce((total, entry) => total + (Array.isArray(entry.tweets) ? entry.tweets.length : 0), 0),
      filteredCount: this.filteredData.length,
      data: this.filteredData,
    };
  }

  async scrape() {
    this.initClient();

    const configuredTerms = this.resolveSearchTerms(this.config.search);
    this.rawData = [];
    this.filteredData = [];
    this.completedTerms = [];
    this.failedTerms = [];
    this.qualityCreatorStats = {
      qualityCreatorCount: 0,
      qualityCreatorHitCount: 0,
      searchQueryCountBeforeReduction: configuredTerms.length,
      searchQueryCountAfterReduction: configuredTerms.length,
      droppedSearchQueries: [],
      dropReasons: {},
    };
    const allTweets = [];
    const termBuckets = [];
    const seen = new Set();

    const creators = await this.loadQualityCreators();
    const creatorBuckets = await this.fetchQualityCreatorTweets(creators, seen);
    termBuckets.push(...creatorBuckets);

    const reduction = selectSearchQueriesAfterCreatorHits(
      configuredTerms,
      this.qualityCreatorStats.qualityCreatorHitCount,
      this.config.qualityCreators || {}
    );
    const terms = reduction.selectedQueries;
    this.qualityCreatorStats.searchQueryCountBeforeReduction = reduction.beforeCount;
    this.qualityCreatorStats.searchQueryCountAfterReduction = reduction.afterCount;
    this.qualityCreatorStats.droppedSearchQueries = reduction.droppedSearchQueries;
    this.qualityCreatorStats.dropReasons = reduction.dropReasons;

    if (reduction.droppedSearchQueries.length) {
      console.log(
        `Quality creator hits reduced X search terms from ${reduction.beforeCount} to ${reduction.afterCount}; dropped: ${reduction.droppedSearchQueries.join(", ")}`
      );
      this.saveCheckpoint("partial", { ...this.qualityCreatorStats });
    }

    if (!terms.length && !creatorBuckets.length) {
      throw new Error("No searchTerms configured and no quality creator posts available");
    }

    const maxPagesPerTerm = Math.max(1, safeNumber(this.config.search.pagesPerTerm || 1));
    const minFilteredPerTerm = Math.max(0, safeNumber(this.config.search.minFilteredPerTerm || 0));
    const maxFilteredPerTerm = Math.max(
      minFilteredPerTerm,
      safeNumber(this.config.search.maxFilteredPerTerm || this.config.search.count || 20)
    );
    const theoreticalMaxRequests = terms.length * maxPagesPerTerm;

    console.log(
      `Starting X search scrape via RapidAPI for ${terms.length} search terms (pagesPerTerm=${maxPagesPerTerm}, maxRequests=${theoreticalMaxRequests})...`
    );
    for (const [index, term] of terms.entries()) {
      console.log(`[${index + 1}/${terms.length}] Fetching "${term}"`);
      let cursor = this.config.search.cursor || "";
      const termFilteredTweets = [];
      const termFilteredSeen = new Set();
      let termBucketPushed = false;

      for (let pageIndex = 0; pageIndex < maxPagesPerTerm; pageIndex += 1) {
        let payload;
        try {
          payload = await this.fetchSearchPage(term, cursor);
        } catch (error) {
          this.markFailedTerm(term, pageIndex + 1, error);
          this.saveCheckpoint("partial", { error: formatErrorDetails(error) || String(error) });
          if (this.partialContinue && this.rawData.length) {
            if (termFilteredTweets.length && !termBucketPushed) {
              termBuckets.push({
                search_term: term,
                filtered_count: termFilteredTweets.length,
                fallback_added: 0,
                partial: true,
                tweets: termFilteredTweets,
              });
              termBucketPushed = true;
            }
            console.warn(`X scrape failed after partial data; continuing with ${this.rawData.length} raw pages.`);
            return this.finalizeScrape(terms, termBuckets, "partial", { error: formatErrorDetails(error) || String(error) });
          }
          throw error;
        }
        const tweets = extractTweetsFromPayload(payload, term);
        const pageFilteredTweets = [];
        this.rawData.push({
          capture_source: "search",
          search_term: term,
          page: pageIndex + 1,
          cursor: cursor || "",
          fetched_at: new Date().toISOString(),
          tweets,
        });

        for (const tweet of tweets) {
          if (seen.has(tweet.id)) {
            // Keep scanning because the same post can appear under multiple terms/pages.
          } else {
            seen.add(tweet.id);
            allTweets.push(tweet);
          }

          if (!this.filterItem(tweet)) {
            continue;
          }
          if (termFilteredSeen.has(tweet.id)) {
            continue;
          }

          termFilteredSeen.add(tweet.id);
          pageFilteredTweets.push(tweet);
          if (termFilteredTweets.length < maxFilteredPerTerm) {
            termFilteredTweets.push(this.buildRankedTweetForTerm(tweet, term, "strict"));
          }
        }

        this.rawData[this.rawData.length - 1].filtered_tweet_ids = pageFilteredTweets.map((tweet) => tweet.id);
        this.rawData[this.rawData.length - 1].filtered_count = pageFilteredTweets.length;
        this.markCompletedTerm(term, pageIndex + 1);
        this.saveCheckpoint("partial");

        cursor = findNextCursor(payload);
        if (termFilteredTweets.length >= maxFilteredPerTerm) {
          break;
        }
        if (termFilteredTweets.length >= minFilteredPerTerm) {
          break;
        }
        if (!cursor) {
          break;
        }
      }

      termBuckets.push({
        search_term: term,
        filtered_count: termFilteredTweets.length,
        fallback_added: 0,
        tweets: termFilteredTweets,
      });
      termBucketPushed = true;

      if (termFilteredTweets.length < minFilteredPerTerm) {
        console.warn(
          `Warning: "${term}" only yielded ${termFilteredTweets.length} filtered posts (target minimum: ${minFilteredPerTerm})`
        );
      } else {
        console.log(
          `  -> kept ${termFilteredTweets.length} filtered posts for "${term}" (target range: ${minFilteredPerTerm}-${maxFilteredPerTerm}, fallback added: 0)`
        );
      }
    }

    return this.finalizeScrape(terms, termBuckets, "full", { rawCount: allTweets.length });
  }

  filterItem(item, options = {}) {
    const filters = this.config.filters || {};
    const mode = options.mode === "fallback" ? "fallback" : "strict";
    const hardMaxVideoDurationSeconds = 30;
    if (!item.id || !item.url || !item.text) {
      return false;
    }
    if (!item.has_visual_media) {
      return false;
    }
    if (safeNumber(item.view_count) < safeNumber(filters.minViewCount)) {
      return false;
    }
    if (safeNumber(item.like_count) < safeNumber(filters.minLikeCount)) {
      return false;
    }
    const durationSeconds = safeNumber(item.video_duration_seconds);
    if (durationSeconds > hardMaxVideoDurationSeconds) {
      return false;
    }
    if (safeNumber(filters.maxVideoDurationSeconds) > 0) {
      if (durationSeconds > safeNumber(filters.maxVideoDurationSeconds)) {
        return false;
      }
    }

    const targetDate = parseTargetDate(filters.targetDate);
    const createdAt = parseCreatedAt(item.created_at);
    if (targetDate) {
      if (!createdAt || dateInShanghai(createdAt) !== targetDate) {
        return false;
      }
    }

    const maxHoursAgo = safeNumber(filters.maxHoursAgo);
    if (maxHoursAgo > 0) {
      if (!createdAt) {
        return false;
      }
      const ageHours = (Date.now() - createdAt.getTime()) / 3600000;
      if (ageHours < 0 || ageHours > maxHoursAgo) {
        return false;
      }
    }

    const minRecentLikes =
      mode === "fallback"
        ? safeNumber(filters.fallbackMinLikeCount)
        : safeNumber(filters.recentMinLikeCount);
    const minRecentRetweets =
      mode === "fallback"
        ? safeNumber(filters.fallbackMinRetweetCount)
        : safeNumber(filters.recentMinRetweetCount);
    if (minRecentLikes > 0 || minRecentRetweets > 0) {
      const likes = safeNumber(item.like_count);
      const retweets = safeNumber(item.retweet_count);
      if (likes < minRecentLikes && retweets < minRecentRetweets) {
        return false;
      }
    }

    return true;
  }

  saveRawData(terms) {
    const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
    const safeTerms = terms
      .join("_")
      .replace(/[<>:"/\\|?*]+/g, "-")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 120) || "x";
    const filename = `raw_${safeTerms}_${timestamp}.json`;
    const filepath = path.join(this.config.dataDir, "raw", filename);
    fs.writeFileSync(filepath, JSON.stringify(this.rawData, null, 2), "utf-8");
    return filepath;
  }

  saveFilteredData() {
    const filepath = path.join(this.config.dataDir, "filtered-result.json");
    fs.writeFileSync(filepath, JSON.stringify(this.filteredData, null, 2), "utf-8");
    return filepath;
  }
}

async function main() {
  loadEnvFile();
  const configPath = path.join(__dirname, "..", "config", "config.json");
  let userConfig = {};
  if (fs.existsSync(configPath)) {
    userConfig = JSON.parse(fs.readFileSync(configPath, "utf-8"));
  }

  const rules = loadFeedbackRules();
  const ruleScrape = getRuleScrapeConfig(rules);
  const searchConfig = { ...CONFIG.search, ...(userConfig.search || {}) };
  const qualityCreatorConfig = {
    ...CONFIG.qualityCreators,
    ...(userConfig.qualityCreators || {}),
    ...(userConfig.quality_creators || {}),
  };
  const filterConfig = { ...CONFIG.filters, ...(userConfig.filters || {}) };
  if (ruleScrape.searchQueries.length) {
    searchConfig.searchTerms = ruleScrape.searchQueries;
  }
  if (typeof ruleScrape.qualityCreators.enabled === "boolean") {
    qualityCreatorConfig.enabled = ruleScrape.qualityCreators.enabled;
  }
  qualityCreatorConfig.sheetUrl =
    process.env.X_QUALITY_CREATORS_SHEET_URL ||
    ruleScrape.qualityCreators.sheetUrl ||
    qualityCreatorConfig.sheetUrl;
  qualityCreatorConfig.maxAccounts = envNumber(
    "X_QUALITY_CREATORS_MAX_ACCOUNTS",
    ruleScrape.qualityCreators.maxAccounts || qualityCreatorConfig.maxAccounts
  );
  qualityCreatorConfig.postsPerAccount = envNumber(
    "X_QUALITY_CREATORS_POSTS_PER_ACCOUNT",
    ruleScrape.qualityCreators.postsPerAccount || qualityCreatorConfig.postsPerAccount
  );
  qualityCreatorConfig.pagesPerAccount = envNumber(
    "X_QUALITY_CREATORS_PAGES_PER_ACCOUNT",
    ruleScrape.qualityCreators.pagesPerAccount || qualityCreatorConfig.pagesPerAccount
  );
  qualityCreatorConfig.reduceQueriesPerHit = envNumber(
    "X_QUALITY_CREATORS_REDUCE_QUERIES_PER_HIT",
    ruleScrape.qualityCreators.reduceQueriesPerHit || qualityCreatorConfig.reduceQueriesPerHit
  );
  qualityCreatorConfig.minSearchQueries = envNumber(
    "X_QUALITY_CREATORS_MIN_SEARCH_QUERIES",
    ruleScrape.qualityCreators.minSearchQueries || qualityCreatorConfig.minSearchQueries
  );
  qualityCreatorConfig.enabled = envBool("X_QUALITY_CREATORS_ENABLED", Boolean(qualityCreatorConfig.enabled));
  searchConfig.maxSearchQueries = ruleScrape.maxSearchQueries || envNumber("X_MAX_SEARCH_QUERIES", searchConfig.maxSearchQueries || 20);
  searchConfig.count = envNumber("X_SEARCH_COUNT", ruleScrape.resultsPerKeyword || searchConfig.count);
  searchConfig.pagesPerTerm = envNumber("X_PAGES_PER_TERM", searchConfig.pagesPerTerm);
  searchConfig.minFilteredPerTerm = envNumber("X_MIN_FILTERED_PER_TERM", searchConfig.minFilteredPerTerm || 0);
  searchConfig.maxFilteredPerTerm = envNumber("X_MAX_FILTERED_PER_TERM", searchConfig.maxFilteredPerTerm || searchConfig.count);
  filterConfig.maxHoursAgo = envNumber("X_MAX_HOURS_AGO", filterConfig.maxHoursAgo);
  filterConfig.maxVideoDurationSeconds = envNumber("X_MAX_VIDEO_DURATION_SECONDS", filterConfig.maxVideoDurationSeconds || 30);
  const targetDate = parseTargetDate(process.env.TARGET_DATE);
  if (targetDate) {
    const untilDate = nextIsoDate(targetDate);
    searchConfig.searchTerms = (searchConfig.searchTerms || []).map((term) => {
      const cleanTerm = stripDateOperators(term);
      return `${cleanTerm} since:${targetDate} until:${untilDate}`;
    });
    filterConfig.maxHoursAgo = 0;
    filterConfig.targetDate = targetDate;
  }

  const scraper = new XScraper({
    rapidApiKey: process.env.X_RAPIDAPI_KEY || userConfig.rapidApiKey,
    rapidApiHost: process.env.X_RAPIDAPI_HOST || userConfig.rapidApiHost || CONFIG.rapidApiHost,
    partialContinue: envBool("SCRAPE_PARTIAL_CONTINUE", true),
    runId: runIdFromEnv(),
    search: searchConfig,
    qualityCreators: qualityCreatorConfig,
    filters: filterConfig,
  });

  console.log("=".repeat(48));
  console.log("X Scraper (RapidAPI)");
  console.log("=".repeat(48));

  try {
    const result = await scraper.scrape();
    console.log(`Raw posts: ${result.rawCount}`);
    console.log(`Clean posts: ${result.filteredCount}`);
    console.log("X scrape complete");
  } catch (error) {
    console.error(`X scrape failed: ${formatErrorDetails(error) || error.message}`);
    process.exit(1);
  }
}

module.exports = {
  CONFIG,
  XScraper,
  extractTweetsFromPayload,
  findNextCursor,
  extractXUsername,
  readQualityCreatorsFromFeishu,
  selectSearchQueriesAfterCreatorHits,
  rankSearchQueriesForReduction,
};

if (require.main === module) {
  main();
}
