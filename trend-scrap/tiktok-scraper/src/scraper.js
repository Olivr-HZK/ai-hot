const fs = require("fs");
const path = require("path");
const apifyClientModule = require("apify-client");
const ApifyClient = apifyClientModule.ApifyClient || apifyClientModule.default || apifyClientModule;

const ROOT_DIR = path.resolve(__dirname, "..", "..", "..");
const DATA_DIR = path.join(__dirname, "..", "data");
const DEFAULT_CHECKPOINT_ROOT = path.join(ROOT_DIR, "skill_runs", "scrape_checkpoints");

function loadRootEnv() {
  const envPath = path.join(ROOT_DIR, ".env");
  if (!fs.existsSync(envPath)) return;
  for (const rawLine of fs.readFileSync(envPath, "utf-8").split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const [key, ...rest] = line.split("=");
    const cleanKey = key.trim();
    let value = rest.join("=").trim();
    if (value.length >= 2 && ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'")))) {
      value = value.slice(1, -1);
    }
    if (cleanKey && !process.env[cleanKey]) process.env[cleanKey] = value;
  }
}

loadRootEnv();

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

function hotFeedDir() {
  return resolveRepoPath(process.env.TIKTOK_HOT_FEED_OUTPUT_DIR || "skill_runs/tiktok_hot_feed", path.join(ROOT_DIR, "skill_runs", "tiktok_hot_feed"));
}

function runIdFromEnv() {
  return process.env.PIPELINE_RUN_ID || new Date().toISOString().replace(/[-:T.]/g, "").slice(0, 14);
}

const APIFY_QUOTA_ERROR_PATTERNS = [
  /remaining usage/i,
  /usage limit/i,
  /usage hard limit/i,
  /monthly usage/i,
  /hard limit/i,
  /limit exceeded/i,
  /exceeded.*limit/i,
  /quota/i,
  /insufficient (usage|credits|balance|funds)/i,
  /not enough (credits|balance|funds)/i,
  /billing\/subscription/i,
  /payment required/i,
  /outstanding invoices/i,
  /too many outstanding invoices/i,
];

const RAPIDAPI_QUOTA_ERROR_PATTERNS = [/quota/i, /rate limit/i, /too many requests/i, /exceeded.*requests/i, /plan limit/i, /payment required/i, /subscription/i, /forbidden/i];

function parseTokenPool(raw) {
  if (!raw) return [];
  return String(raw).split(/[\n,;]+/).map((value) => value.trim().replace(/^['"]|['"]$/g, "")).filter(Boolean);
}

function uniqueTokens(tokens) {
  const seen = new Set();
  const result = [];
  for (const token of tokens) {
    if (!token || seen.has(token)) continue;
    seen.add(token);
    result.push(token);
  }
  return result;
}

function maskToken(token) {
  if (!token) return "<empty>";
  if (token.length <= 14) return `${token.slice(0, 4)}...`;
  return `${token.slice(0, 8)}...${token.slice(-6)}`;
}

function getErrorMessage(error) {
  return [error && error.message, error && error.response && error.response.data && error.response.data.message, error && error.response && error.response.data && error.response.data.error, error && error.cause && error.cause.message].filter(Boolean).join(" | ") || String(error);
}

function getStatus(error) {
  const status = error && (error.statusCode || error.status || (error.response && error.response.status));
  const parsed = Number.parseInt(status, 10);
  return Number.isFinite(parsed) ? parsed : null;
}

function isApifyQuotaError(error) {
  const message = getErrorMessage(error);
  const status = getStatus(error);
  return APIFY_QUOTA_ERROR_PATTERNS.some((pattern) => pattern.test(message)) || status === 402;
}

function isRapidApiQuotaError(error) {
  const message = getErrorMessage(error);
  const status = getStatus(error);
  return RAPIDAPI_QUOTA_ERROR_PATTERNS.some((pattern) => pattern.test(message)) || [402, 403, 429].includes(status);
}

function keyPoolError(message, code) {
  const error = new Error(message);
  error.code = code;
  return error;
}

function ensureDirs() {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  fs.mkdirSync(path.join(DATA_DIR, "raw"), { recursive: true });
}

function safeNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function firstValue(source, keys, fallback = "") {
  if (!source || typeof source !== "object") return fallback;
  for (const key of keys) {
    const value = source[key];
    if (value !== undefined && value !== null && value !== "") return value;
  }
  return fallback;
}

function firstString(source, keys, fallback = "") {
  const value = firstValue(source, keys, fallback);
  return typeof value === "string" ? value : fallback;
}

function nestedValue(source, paths, fallback = "") {
  if (!source || typeof source !== "object") return fallback;
  for (const pathParts of paths) {
    let current = source;
    for (const key of pathParts) {
      if (!current || typeof current !== "object" || !(key in current)) {
        current = undefined;
        break;
      }
      current = current[key];
    }
    if (current !== undefined && current !== null && current !== "") return current;
  }
  return fallback;
}

function coverUrlFromValue(value) {
  if (!value) return "";
  if (typeof value === "string") return value;
  if (typeof value === "object") {
    if (typeof value.uri === "string" && value.uri) return value.uri;
    if (typeof value.url === "string" && value.url) return value.url;
    if (Array.isArray(value.url_list) && value.url_list.length) return String(value.url_list[0] || "");
  }
  return "";
}

function normalizeDurationSeconds(value) {
  const number = safeNumber(value);
  if (number > 1000) return number / 1000;
  return number;
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
  const scrape = rules && typeof rules === "object" ? rules.scrape || {} : {};
  const queries = Array.isArray(scrape.search_queries) ? scrape.search_queries.map((query) => String(query || "").trim()).filter(Boolean) : [];
  const resultsPerKeyword = Number.parseInt(scrape.results_per_keyword, 10);
  const maxSearchQueries = Number.parseInt(scrape.max_search_queries, 10);
  const rawAllocations = scrape.keyword_allocations && typeof scrape.keyword_allocations === "object" ? scrape.keyword_allocations : {};
  const keywordAllocations = {};
  for (const [query, value] of Object.entries(rawAllocations)) {
    const key = String(query || "").trim().toLowerCase();
    const count = Number.parseInt(value, 10);
    if (key && Number.isFinite(count) && count > 0) keywordAllocations[key] = count;
  }
  const rawHotFeed = scrape.hot_feed && typeof scrape.hot_feed === "object" ? scrape.hot_feed : {};
  const hotFeedEnabled = rawHotFeed.enabled === undefined ? false : /^(1|true|yes|y|on)$/i.test(String(rawHotFeed.enabled));
  const hotFeedMaxItems = Number.parseInt(rawHotFeed.max_items, 10);
  const hotFeedMaxPages = Number.parseInt(rawHotFeed.max_pages, 10);
  return {
    searchQueries: queries,
    resultsPerKeyword: Number.isFinite(resultsPerKeyword) && resultsPerKeyword > 0 ? resultsPerKeyword : null,
    maxSearchQueries: Number.isFinite(maxSearchQueries) && maxSearchQueries > 0 ? maxSearchQueries : null,
    keywordAllocations,
    hotFeed: {
      enabled: hotFeedEnabled,
      maxItems: Number.isFinite(hotFeedMaxItems) && hotFeedMaxItems > 0 ? hotFeedMaxItems : 100,
      maxPages: Number.isFinite(hotFeedMaxPages) && hotFeedMaxPages > 0 ? hotFeedMaxPages : 1,
      path: String(rawHotFeed.path || "").trim(),
      method: String(rawHotFeed.method || "GET").trim().toUpperCase() || "GET",
    },
  };
}

function normalizeSearchQueries(queries, maxSearchQueries = 10) {
  const limit = Math.min(10, Math.max(1, safeNumber(maxSearchQueries || 10)));
  const seen = new Set();
  const normalized = [];
  for (const query of queries || []) {
    const value = String(query || "").trim();
    const key = value.toLowerCase();
    if (!value || seen.has(key)) continue;
    seen.add(key);
    normalized.push(value);
  }
  if (normalized.length > limit) {
    console.warn(`TikTok search terms capped at ${limit}; ${normalized.length - limit} extra terms were skipped.`);
  }
  return normalized.slice(0, limit);
}

function loadConfig() {
  const configPath = path.join(__dirname, "..", "config", "config.json");
  if (!fs.existsSync(configPath)) return {};
  return JSON.parse(fs.readFileSync(configPath, "utf-8"));
}

class TikTokScraper {
  constructor(config) {
    this.config = config;
    this.apifyTokens = uniqueTokens([config.apifyToken, ...parseTokenPool(config.apifyTokenPool), ...parseTokenPool(config.apifyTokens)]);
    this.rapidApiTokens = uniqueTokens([config.rapidApiKey, config.rapidApiKey2]);
    this.hotFeedRapidApiTokens = uniqueTokens([config.rapidApiHotFeedKey]);
    this.currentApifyIndex = 0;
    this.currentRapidIndex = 0;
    this.client = null;
    this.rawData = [];
    this.filteredData = [];
    this.runId = config.runId || runIdFromEnv();
    this.completedQueries = [];
    this.failedQueries = [];
    this.hotFeedItemCount = 0;
    this.hotFeedError = "";
    this.partialContinue = config.partialContinue !== undefined ? Boolean(config.partialContinue) : envBool("SCRAPE_PARTIAL_CONTINUE", true);
    ensureDirs();
  }

  keywordLimit(query) {
    const key = String(query || "").trim().toLowerCase();
    const configured = this.config.keywordAllocations && this.config.keywordAllocations[key];
    const count = Number.parseInt(configured || this.config.resultsPerKeyword, 10);
    return Number.isFinite(count) && count > 0 ? count : 35;
  }

  keywordAllocationReport(queries) {
    const report = {};
    for (const query of queries || []) {
      report[query] = this.keywordLimit(query);
    }
    return report;
  }

  initApifyClient() {
    const token = this.apifyTokens[this.currentApifyIndex];
    if (!token) throw keyPoolError("APIFY_TOKEN or APIFY_TOKEN_POOL is required", "APIFY_TOKENS_MISSING");
    this.client = new ApifyClient({ token });
    console.log(`Using Apify key #${this.currentApifyIndex + 1}/${this.apifyTokens.length} (${maskToken(token)})`);
  }

  async withApifyFallback(operation, context) {
    while (true) {
      if (!this.client) this.initApifyClient();
      try {
        return await operation();
      } catch (error) {
        if (!isApifyQuotaError(error)) throw error;
        if (this.currentApifyIndex >= this.apifyTokens.length - 1) throw keyPoolError(`All Apify keys exhausted during ${context}`, "APIFY_TOKENS_EXHAUSTED");
        this.currentApifyIndex += 1;
        this.initApifyClient();
      }
    }
  }

  async fetchApifyItems(query, params) {
    return this.withApifyFallback(async () => {
      const limit = this.keywordLimit(query);
      const run = await this.client.actor(this.config.actorId).call({ ...params, searchQueries: [query], resultsPerPage: limit });
      const list = await this.client.dataset(run.defaultDatasetId).listItems();
      return list.items || [];
    }, `query ${query}`);
  }

  rapidKey() {
    return this.rapidApiTokens[this.currentRapidIndex] || "";
  }

  async withRapidApiFallback(operation, context) {
    while (true) {
      const token = this.rapidKey();
      if (!token) throw keyPoolError("RAPIDAPI_KEY or RAPIDAPI_KEY_2 is required for TikTok RapidAPI fallback", "RAPIDAPI_TOKENS_EXHAUSTED");
      try {
        return await operation(token);
      } catch (error) {
        if (!isRapidApiQuotaError(error)) throw error;
        const message = getErrorMessage(error);
        console.warn(`RapidAPI key #${this.currentRapidIndex + 1}/${this.rapidApiTokens.length} failed during ${context}: ${message}`);
        if (this.currentRapidIndex >= this.rapidApiTokens.length - 1) throw keyPoolError(`All RapidAPI keys exhausted during ${context}: ${message}`, "RAPIDAPI_TOKENS_EXHAUSTED");
        this.currentRapidIndex += 1;
      }
    }
  }

  async withHotFeedRapidApi(operation, context) {
    const token = this.hotFeedRapidApiTokens[0];
    if (!token) throw keyPoolError("RAPIDAPI_TIKTOK_HOT_FEED_KEY is required for TikTok hot feed", "RAPIDAPI_HOT_FEED_TOKEN_MISSING");
    try {
      return await operation(token);
    } catch (error) {
      const message = getErrorMessage(error);
      throw keyPoolError(`TikTok hot feed request failed during ${context}: ${message}`, "RAPIDAPI_HOT_FEED_FAILED");
    }
  }

  async withSocialCrawlHotFeed(operation, context) {
    const token = this.config.socialCrawlApiKey || "";
    if (!token) throw keyPoolError("SOCIALCRAWL_API_KEY is required for SocialCrawl TikTok hot feed", "SOCIALCRAWL_TOKEN_MISSING");
    try {
      return await operation(token);
    } catch (error) {
      const message = getErrorMessage(error);
      throw keyPoolError(`SocialCrawl TikTok hot feed request failed during ${context}: ${message}`, "SOCIALCRAWL_HOT_FEED_FAILED");
    }
  }

  normalizeRapidApiItem(item) {
    const id = String(item && item.id ? item.id : "");
    const authorId = (item && item.author && (item.author.uniqueId || item.author.id)) || "user";
    const stats = (item && (item.stats || item.statsV2)) || {};
    return {
      id,
      text: (item && (item.desc || (item.contents && item.contents[0] && item.contents[0].desc))) || "",
      textLanguage: (item && item.textLanguage) || "unknown",
      hashtags: Array.isArray(item && item.challenges) ? item.challenges.map((tag) => tag.title).filter(Boolean) : [],
      diggCount: safeNumber(stats.diggCount || stats.likeCount),
      shareCount: safeNumber(stats.shareCount),
      commentCount: safeNumber(stats.commentCount),
      playCount: safeNumber(stats.playCount),
      videoMeta: { duration: normalizeDurationSeconds(item && item.video && item.video.duration), downloadAddr: (item && item.video && (item.video.downloadAddr || item.video.playAddr)) || "", webVideoUrl: id ? `https://www.tiktok.com/@${authorId}/video/${id}` : "", coverUrl: (item && item.video && (item.video.cover || item.video.originCover || item.video.dynamicCover)) || "" },
      webVideoUrl: id ? `https://www.tiktok.com/@${authorId}/video/${id}` : "",
      mediaUrls: [item && item.video && (item.video.cover || item.video.originCover || item.video.dynamicCover)].filter(Boolean),
      authorMeta: { nickName: (item && item.author && (item.author.nickname || item.author.uniqueId)) || "", fans: safeNumber(item && item.authorStats && item.authorStats.followerCount) },
      createTime: item && item.createTime ? item.createTime : "",
      createTimeISO: "",
      sourcePath: "rapidapi",
      captureSource: "search",
    };
  }

  extractRapidApiItems(payload) {
    if (Array.isArray(payload)) return payload;
    if (!payload || typeof payload !== "object") return [];
    const directKeys = ["item_list", "itemList", "items", "videos", "aweme_list", "awemeList", "results"];
    for (const key of directKeys) {
      if (Array.isArray(payload[key])) return payload[key];
    }
    const data = payload.data;
    if (Array.isArray(data)) return data;
    if (data && typeof data === "object") {
      for (const key of directKeys) {
        if (Array.isArray(data[key])) return data[key];
      }
    }
    return [];
  }

  normalizeSocialCrawlItem(item, region) {
    const raw = item && typeof item === "object" ? item : {};
    const stats = raw.statistics && typeof raw.statistics === "object" ? raw.statistics : {};
    const video = raw.video && typeof raw.video === "object" ? raw.video : {};
    const author = raw.author && typeof raw.author === "object" ? raw.author : {};
    const id = String(firstValue(raw, ["id", "aweme_id", "videoId", "video_id", "postId"], ""));
    const username = firstString(author, ["username", "uniqueId", "unique_id", "handle"], "");
    const rawUrl = firstString(raw, ["url", "webVideoUrl", "shareUrl", "videoUrl", "postUrl"], "");
    const fallbackUrl = id && username ? `https://www.tiktok.com/@${username.replace(/^@/, "")}/video/${id}` : "";
    const coverUrl = coverUrlFromValue(firstValue(raw, ["coverUrl", "thumbnail", "thumbnailUrl", "cover"], nestedValue(video, [["cover"], ["origin_cover"], ["dynamic_cover"]], "")));
    return {
      id,
      text: firstString(raw, ["text", "desc", "description", "caption", "title"], ""),
      textLanguage: firstString(raw, ["language", "textLanguage"], "unknown"),
      hashtags: Array.isArray(raw.challenges) ? raw.challenges.map((tag) => tag && tag.title).filter(Boolean) : [],
      diggCount: safeNumber(firstValue(raw, ["diggCount", "digg_count", "likeCount", "likes"], firstValue(stats, ["diggCount", "digg_count", "likes"], 0))),
      shareCount: safeNumber(firstValue(raw, ["shareCount", "share_count", "shares"], firstValue(stats, ["shareCount", "share_count", "shares"], 0))),
      commentCount: safeNumber(firstValue(raw, ["commentCount", "comment_count", "comments"], firstValue(stats, ["commentCount", "comment_count", "comments"], 0))),
      playCount: safeNumber(firstValue(raw, ["playCount", "play_count", "viewCount", "views"], firstValue(stats, ["playCount", "play_count", "views"], 0))),
      videoMeta: {
        duration: normalizeDurationSeconds(firstValue(raw, ["duration"], firstValue(video, ["duration"], 0))),
        downloadAddr: nestedValue(video, [["download_addr", "url_list", 0], ["play_addr", "url_list", 0]], ""),
        webVideoUrl: rawUrl || fallbackUrl,
        coverUrl,
      },
      webVideoUrl: rawUrl || fallbackUrl,
      mediaUrls: [coverUrl].filter(Boolean),
      authorMeta: {
        nickName: firstString(author, ["nickname", "nickName", "name"], username),
        uniqueId: username,
        fans: safeNumber(firstValue(author, ["followers", "followerCount", "fans"], 0)),
      },
      createTime: firstValue(raw, ["createTime", "create_time", "createdAt", "timestamp"], ""),
      createTimeISO: firstString(raw, ["create_time_utc", "createTimeISO"], ""),
      sourcePath: "socialcrawl_hot_feed",
      sourceQuery: "hot_feed",
      captureSource: "hot_feed",
      hotFeedProvider: "socialcrawl",
      hotFeedRegion: String(region || "").toUpperCase(),
      raw_source: raw,
    };
  }

  extractSocialCrawlItems(payload) {
    return this.extractRapidApiItems(payload);
  }

  saveHotFeedRaw(source, payload, items, meta = {}) {
    const dir = hotFeedDir();
    const latestPath = path.join(dir, "latest_raw.json");
    const archivePath = path.join(dir, "runs", `${this.runId}_raw.json`);
    const report = {
      schemaVersion: 1,
      platform: "tiktok",
      source,
      runId: this.runId,
      fetchedAt: new Date().toISOString(),
      itemCount: Array.isArray(items) ? items.length : 0,
      normalizedItems: items,
      rawResponse: payload,
      ...meta,
    };
    writeJsonAtomic(latestPath, report);
    writeJsonAtomic(archivePath, report);
  }

  async fetchSocialCrawlHotFeed() {
    const hotFeed = this.config.hotFeed || {};
    if (!hotFeed.enabled || !this.config.socialCrawlHotFeedEnabled || !this.config.socialCrawlApiKey) return [];
    const endpoint = this.config.socialCrawlTrendingUrl || "https://socialcrawl.dev/v1/tiktok/trending";
    const region = this.config.socialCrawlRegion || "US";
    const trim = this.config.socialCrawlTrim !== undefined ? String(this.config.socialCrawlTrim) : "true";
    const maxItems = Math.max(1, Math.min(200, Number.parseInt(hotFeed.maxItems || this.config.socialCrawlMaxItems || 100, 10)));
    return this.withSocialCrawlHotFeed(async (token) => {
      const params = new URLSearchParams({ region: String(region).toUpperCase(), trim });
      const response = await fetch(`${endpoint}?${params.toString()}`, {
        method: "GET",
        headers: { "x-api-key": token },
      });
      const text = await response.text();
      let payload = {};
      try {
        payload = text ? JSON.parse(text) : {};
      } catch (error) {
        payload = { raw: text };
      }
      if (!response.ok) {
        const err = new Error(payload.message || payload.error || `SocialCrawl HTTP ${response.status}`);
        err.status = response.status;
        throw err;
      }
      const normalizedItems = this.extractSocialCrawlItems(payload)
        .map((item) => this.normalizeSocialCrawlItem(item, region))
        .slice(0, maxItems);
      this.saveHotFeedRaw("socialcrawl_hot_feed", payload, normalizedItems, {
        endpoint,
        region: String(region).toUpperCase(),
        trim,
        estimatedCredits: 5,
        creditsUsed: payload.credits_used || response.headers.get("x-credits-used") || "",
        creditsRemaining: payload.credits_remaining || response.headers.get("x-credits-remaining") || "",
        cached: payload.cached || response.headers.get("x-cache") === "HIT",
      });
      return normalizedItems;
    }, "socialcrawl trending");
  }

  async fetchHotFeed() {
    const socialItems = await this.fetchSocialCrawlHotFeed();
    if (socialItems.length) return { items: socialItems, source: "socialcrawl_hot_feed" };
    const rapidItems = await this.fetchRapidApiHotFeed();
    return { items: rapidItems, source: "rapidapi_hot_feed" };
  }

  async fetchRapidApiItems(query) {
    const host = this.config.rapidApiHost;
    const pathName = this.config.rapidApiSearchPath;
    const count = Math.min(30, Math.max(1, this.keywordLimit(query)));
    return this.withRapidApiFallback(async (token) => {
      const params = new URLSearchParams({ keyword: query, cursor: "0", count: String(count) });
      const response = await fetch(`https://${host}${pathName}?${params.toString()}`, { headers: { "x-rapidapi-key": token, "x-rapidapi-host": host } });
      const text = await response.text();
      let payload = {};
      try {
        payload = text ? JSON.parse(text) : {};
      } catch (error) {
        payload = { raw: text };
      }
      if (!response.ok) {
        const err = new Error(payload.message || payload.error || `RapidAPI HTTP ${response.status}`);
        err.status = response.status;
        throw err;
      }
      const statusCode = Number.parseInt(payload.statusCode, 10);
      if (Number.isFinite(statusCode) && statusCode !== 0 && statusCode !== 10221) throw new Error(payload.message || `RapidAPI business status ${statusCode}`);
      const items = Array.isArray(payload.item_list) ? payload.item_list : Array.isArray(payload.itemList) ? payload.itemList : [];
      return items.map((item) => this.normalizeRapidApiItem(item));
    }, `query ${query}`);
  }

  async fetchRapidApiHotFeed() {
    const hotFeed = this.config.hotFeed || {};
    if (!hotFeed.enabled) return [];
    let pathName = this.config.rapidApiHotFeedPath || hotFeed.path || "";
    if (!pathName) {
      console.warn("TikTok hot feed is enabled but RAPIDAPI_TIKTOK_HOT_FEED_PATH / scrape.hot_feed.path is empty; skipping hot feed source.");
      return [];
    }
    if (/^https?:\/\//i.test(pathName)) {
      try {
        const parsed = new URL(pathName);
        pathName = `${parsed.pathname}${parsed.search}`;
      } catch (_error) {
        console.warn("TikTok hot feed path looked like a URL but could not be parsed; using it as a path.");
      }
    }
    if (!pathName.startsWith("/")) pathName = `/${pathName}`;
    const host = this.config.rapidApiHost;
    const maxPages = Math.max(1, Math.min(5, Number.parseInt(hotFeed.maxPages || 1, 10)));
    const maxItems = Math.max(1, Math.min(200, Number.parseInt(hotFeed.maxItems || 100, 10)));
    const perPage = Math.ceil(maxItems / maxPages);
    const collected = [];
    for (let page = 0; page < maxPages && collected.length < maxItems; page += 1) {
      const pageItems = await this.withHotFeedRapidApi(async (token) => {
        const [basePath, rawQuery = ""] = pathName.split("?");
        const params = new URLSearchParams(rawQuery);
        params.set("count", String(perPage));
        params.set("limit", String(perPage));
        params.set("cursor", String(page * perPage));
        params.set("page", String(page + 1));
        const response = await fetch(`https://${host}${basePath}?${params.toString()}`, {
          method: hotFeed.method || "GET",
          headers: { "x-rapidapi-key": token, "x-rapidapi-host": host },
        });
        const text = await response.text();
        let payload = {};
        try {
          payload = text ? JSON.parse(text) : {};
        } catch (error) {
          payload = { raw: text };
        }
        if (!response.ok) {
          const err = new Error(payload.message || payload.error || `RapidAPI hot feed HTTP ${response.status}`);
          err.status = response.status;
          throw err;
        }
        const statusCode = Number.parseInt(payload.statusCode, 10);
        if (Number.isFinite(statusCode) && statusCode !== 0 && statusCode !== 10221) throw new Error(payload.message || `RapidAPI hot feed business status ${statusCode}`);
        return this.extractRapidApiItems(payload).map((item) => {
          const normalized = this.normalizeRapidApiItem(item);
          return { ...normalized, sourcePath: "rapidapi_hot_feed", sourceQuery: "hot_feed", captureSource: "hot_feed" };
        });
      }, `hot feed page ${page + 1}`);
      collected.push(...pageItems);
    }
    return collected.slice(0, maxItems);
  }

  cleanItem(item) {
    const videoMeta = item.videoMeta || {};
    return {
      id: item.id || "",
      text: item.text || item.desc || "",
      textLanguage: item.textLanguage || "unknown",
      hashtags: Array.isArray(item.hashtags) ? item.hashtags : [],
      diggCount: safeNumber(item.diggCount || item.likeCount),
      shareCount: safeNumber(item.shareCount),
      commentCount: safeNumber(item.commentCount),
      playCount: safeNumber(item.playCount),
      videoMeta: { duration: safeNumber(videoMeta.duration), downloadAddr: videoMeta.downloadAddr || "", webVideoUrl: item.webVideoUrl || videoMeta.webVideoUrl || "", coverUrl: videoMeta.coverUrl || videoMeta.originalCoverUrl || videoMeta.thumbnailUrl || "" },
      webVideoUrl: item.webVideoUrl || videoMeta.webVideoUrl || "",
      mediaUrls: Array.isArray(item.mediaUrls) ? item.mediaUrls : [videoMeta.coverUrl || videoMeta.originalCoverUrl || videoMeta.thumbnailUrl].filter(Boolean),
      authorMeta: { nickName: (item.authorMeta && (item.authorMeta.nickName || item.authorMeta.name)) || "", fans: safeNumber(item.authorMeta && item.authorMeta.fans) },
      createTime: item.createTime || "",
      createTimeISO: item.createTimeISO || "",
      comments: Array.isArray(item.comments) ? item.comments : [],
      latestComments: Array.isArray(item.latestComments) ? item.latestComments : [],
      commentsDatasetUrl: item.commentsDatasetUrl || "",
      sourcePath: item.sourcePath || item.source || "apify",
      sourceQuery: item.sourceQuery || item.searchQuery || "",
      captureSource: item.captureSource || (String(item.sourceQuery || "").toLowerCase() === "hot_feed" ? "hot_feed" : "search"),
    };
  }

  filterItem(item) {
    const filters = this.config.filters || {};
    if (item.playCount < safeNumber(filters.minPlayCount)) return false;
    if (item.diggCount < safeNumber(filters.minDiggCount)) return false;
    if (item.shareCount < safeNumber(filters.minShareCount)) return false;
    if (Array.isArray(filters.languages) && filters.languages.length && !filters.languages.includes(item.textLanguage)) return false;
    return true;
  }

  saveRawData(queries) {
    const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
    const safe = queries.slice(0, 6).join("_").replace(/[<>:"/\\|?*\s]+/g, "-").slice(0, 120) || "tiktok";
    fs.writeFileSync(path.join(DATA_DIR, "raw", `raw_${safe}_${timestamp}.json`), JSON.stringify(this.rawData, null, 2), "utf-8");
  }

  saveFilteredData() {
    fs.writeFileSync(path.join(DATA_DIR, "filtered-result.json"), JSON.stringify(this.filteredData, null, 2), "utf-8");
  }

  markCompletedQuery(query, source) {
    const value = `${source}:${query}`;
    if (!this.completedQueries.includes(value)) this.completedQueries.push(value);
  }

  markFailedQuery(query, source, error) {
    const message = getErrorMessage(error);
    this.failedQueries.push({ query, source, message, at: new Date().toISOString() });
  }

  saveCheckpoint(status, extra = {}) {
    const dir = checkpointDir("tiktok");
    const rawPath = path.join(dir, "latest_raw.json");
    const archivePath = path.join(dir, "runs", `${this.runId}_raw.json`);
    const statusPath = path.join(dir, "latest_status.json");
    writeJsonAtomic(rawPath, this.rawData);
    writeJsonAtomic(archivePath, this.rawData);
    writeJsonAtomic(statusPath, {
      platform: "tiktok",
      runId: this.runId,
      status,
      updatedAt: new Date().toISOString(),
      itemCount: this.rawData.length,
      filteredItemCount: this.filteredData.length,
      checkpointPath: rawPath,
      archivePath,
      completed: this.completedQueries,
      failed: this.failedQueries,
      keywordAllocations: this.keywordAllocationReport(this.config.activeQueries || []),
      hotFeed: {
        enabled: Boolean((this.config.hotFeed || {}).enabled),
        itemCount: this.hotFeedItemCount,
        error: this.hotFeedError,
      },
      error: extra.error || "",
      ...extra,
    });
  }

  finalizeScrape(queries, status, extra = {}) {
    this.filteredData = this.rawData.map((item) => this.cleanItem(item)).filter((item) => this.filterItem(item));
    this.saveRawData(queries);
    this.saveFilteredData();
    this.saveCheckpoint(status, { ...extra, filteredItemCount: this.filteredData.length });
    return this.filteredData;
  }

  async scrapeViaRapidApi(queries, options = {}) {
    if (!this.rapidApiTokens.length) throw new Error("Apify exhausted and RapidAPI keys are not configured");
    const fallbackQueries = queries.slice(0, 10);
    if (options.reset !== false || !Array.isArray(this.config.activeQueries) || !this.config.activeQueries.length) {
      this.config.activeQueries = fallbackQueries;
    }
    console.warn(`All Apify quota appears exhausted; switching to RapidAPI fallback for ${fallbackQueries.length} keywords.`);
    if (options.reset !== false) {
      this.rawData = [];
      this.filteredData = [];
      this.completedQueries = [];
      this.failedQueries = [];
      this.hotFeedItemCount = 0;
      this.hotFeedError = "";
    }
    const seen = new Set(this.rawData.map((item) => item && item.id).filter(Boolean));
    if (options.reset !== false) {
      try {
        const hotFeedResult = await this.fetchHotFeed();
        const hotItems = hotFeedResult.items || [];
        for (const item of hotItems) {
          if (item.id && seen.has(item.id)) continue;
          if (item.id) seen.add(item.id);
          this.rawData.push(item);
        }
        this.hotFeedItemCount = hotItems.length;
        if (hotItems.length) {
          this.markCompletedQuery("hot_feed", hotFeedResult.source || "hot_feed");
          this.saveCheckpoint("partial", { source: hotFeedResult.source || "hot_feed" });
          console.log(`Fetched TikTok hot feed candidates: ${hotItems.length}`);
        }
      } catch (hotFeedError) {
        this.hotFeedError = getErrorMessage(hotFeedError);
        this.markFailedQuery("hot_feed", "hot_feed", hotFeedError);
        this.saveCheckpoint("partial", { source: "hot_feed", error: this.hotFeedError });
        console.warn(`TikTok hot feed fetch failed; continuing keyword search: ${this.hotFeedError}`);
      }
    }
    for (const query of fallbackQueries) {
      try {
        const items = await this.fetchRapidApiItems(query);
        for (const item of items) {
          if (item.id && seen.has(item.id)) continue;
          if (item.id) seen.add(item.id);
          this.rawData.push({ ...item, sourceQuery: query });
        }
        this.markCompletedQuery(query, "rapidapi");
        this.saveCheckpoint("partial", { source: "rapidapi" });
      } catch (error) {
        this.markFailedQuery(query, "rapidapi", error);
        this.saveCheckpoint("partial", { source: "rapidapi", error: getErrorMessage(error) });
        if (this.partialContinue && this.rawData.length) {
          console.warn(`RapidAPI fallback failed after partial data; continuing with ${this.rawData.length} raw items.`);
          return this.finalizeScrape(queries, "partial", { source: "rapidapi", error: getErrorMessage(error) });
        }
        throw error;
      }
    }
    return this.finalizeScrape(fallbackQueries, options.statusOnComplete || "full", { source: "rapidapi" });
  }

  async scrape(queries, customParams) {
    const finalQueries = (queries || []).map((query) => String(query || "").trim()).filter(Boolean);
    if (!finalQueries.length) throw new Error("No search queries configured");
    this.config.activeQueries = finalQueries;
    if (this.config.forceRapidApi) return this.scrapeViaRapidApi(finalQueries);
    this.rawData = [];
    this.filteredData = [];
    this.completedQueries = [];
    this.failedQueries = [];
    this.hotFeedItemCount = 0;
    this.hotFeedError = "";
    const seen = new Set();
    const params = { ...(this.config.defaultParams || {}), ...(customParams || {}) };
    let currentQuery = "";
    let currentIndex = 0;
    try {
      try {
        const hotFeedResult = await this.fetchHotFeed();
        const hotItems = hotFeedResult.items || [];
        for (const item of hotItems) {
          if (item.id && seen.has(item.id)) continue;
          if (item.id) seen.add(item.id);
          this.rawData.push(item);
        }
        this.hotFeedItemCount = hotItems.length;
        if (hotItems.length) {
          this.markCompletedQuery("hot_feed", hotFeedResult.source || "hot_feed");
          this.saveCheckpoint("partial", { source: hotFeedResult.source || "hot_feed" });
          console.log(`Fetched TikTok hot feed candidates: ${hotItems.length}`);
        }
      } catch (hotFeedError) {
        this.hotFeedError = getErrorMessage(hotFeedError);
        this.markFailedQuery("hot_feed", "hot_feed", hotFeedError);
        this.saveCheckpoint("partial", { source: "hot_feed", error: this.hotFeedError });
        console.warn(`TikTok hot feed fetch failed; continuing keyword search: ${this.hotFeedError}`);
      }
      if (!this.client) this.initApifyClient();
      for (const [index, query] of finalQueries.entries()) {
        currentQuery = query;
        currentIndex = index;
        console.log(`Fetching TikTok keyword via Apify: ${query} (count=${this.keywordLimit(query)})`);
        const items = await this.fetchApifyItems(query, params);
        for (const item of items) {
          if (item.id && seen.has(item.id)) continue;
          if (item.id) seen.add(item.id);
          this.rawData.push({ ...item, sourcePath: "apify", sourceQuery: query });
        }
        this.markCompletedQuery(query, "apify");
        this.saveCheckpoint("partial", { source: "apify" });
      }
    } catch (error) {
      if (currentQuery) this.markFailedQuery(currentQuery, "apify", error);
      this.saveCheckpoint("partial", { source: "apify", error: getErrorMessage(error) });
      if (error && error.code === "APIFY_TOKENS_EXHAUSTED") {
        const remainingQueries = finalQueries.slice(currentIndex);
        try {
          return await this.scrapeViaRapidApi(remainingQueries, { reset: false, statusOnComplete: "partial" });
        } catch (rapidError) {
          if (this.partialContinue && this.rawData.length) {
            console.warn(`Apify and RapidAPI failed after partial data; continuing with ${this.rawData.length} raw items.`);
            return this.finalizeScrape(finalQueries, "partial", { source: "apify+rapidapi", error: getErrorMessage(rapidError) });
          }
          throw rapidError;
        }
      }
      if (this.partialContinue && this.rawData.length) {
        console.warn(`TikTok scrape failed after partial data; continuing with ${this.rawData.length} raw items.`);
        return this.finalizeScrape(finalQueries, "partial", { source: "apify", error: getErrorMessage(error) });
      }
      throw error;
    }
    return this.finalizeScrape(finalQueries, "full", { source: "apify" });
  }
}

async function main() {
  const userConfig = loadConfig();
  const rules = loadFeedbackRules();
  const ruleScrape = getRuleScrapeConfig(rules);
  const baseParams = userConfig.customParams || {};
  const configuredQueries = ruleScrape.searchQueries.length ? ruleScrape.searchQueries : baseParams.searchQueries || [];
  const queries = normalizeSearchQueries(configuredQueries, ruleScrape.maxSearchQueries || process.env.TIKTOK_MAX_SEARCH_QUERIES || 10);
  const customParams = { ...baseParams, ...(queries.length ? { searchQueries: queries } : {}) };
  const plannedTotal = queries.reduce((sum, query) => sum + (ruleScrape.keywordAllocations[String(query || "").trim().toLowerCase()] || ruleScrape.resultsPerKeyword || userConfig.resultsPerKeyword || 35), 0);
  console.log(`TikTok scrape configured for ${queries.length} search terms (max=10, plannedItems=${plannedTotal}).`);
    const scraper = new TikTokScraper({
    apifyToken: process.env.APIFY_TOKEN || "",
    apifyTokenPool: process.env.APIFY_TOKEN_POOL || process.env.APIFY_TOKENS || "",
    rapidApiKey: process.env.RAPIDAPI_KEY || process.env.RAPIDAPI_TIKTOK_KEY || "",
    rapidApiKey2: process.env.RAPIDAPI_KEY_2 || "",
    rapidApiHost: process.env.RAPIDAPI_TIKTOK_HOST || "tiktok-api23.p.rapidapi.com",
    rapidApiSearchPath: process.env.RAPIDAPI_TIKTOK_SEARCH_PATH || "/api/search/video",
    rapidApiHotFeedKey: process.env.RAPIDAPI_TIKTOK_HOT_FEED_KEY || "",
    rapidApiHotFeedPath: process.env.RAPIDAPI_TIKTOK_HOT_FEED_PATH || "",
    socialCrawlApiKey: process.env.SOCIALCRAWL_API_KEY || "",
    socialCrawlTrendingUrl: process.env.SOCIALCRAWL_TIKTOK_TRENDING_URL || "https://socialcrawl.dev/v1/tiktok/trending",
    socialCrawlHotFeedEnabled: envBool("SOCIALCRAWL_TIKTOK_HOT_FEED_ENABLED", true),
    socialCrawlRegion: process.env.SOCIALCRAWL_TIKTOK_REGION || "US",
    socialCrawlTrim: process.env.SOCIALCRAWL_TIKTOK_TRIM || "true",
    socialCrawlMaxItems: process.env.SOCIALCRAWL_TIKTOK_MAX_ITEMS || "",
    forceRapidApi: /^(1|true|yes)$/i.test(process.env.SCRAPER_FORCE_RAPIDAPI || ""),
    partialContinue: envBool("SCRAPE_PARTIAL_CONTINUE", true),
    runId: runIdFromEnv(),
    actorId: process.env.APIFY_TIKTOK_ACTOR_ID || "GdWCkxBtKWOsKjdch",
    defaultParams: customParams,
    filters: userConfig.filters || {},
    resultsPerKeyword: ruleScrape.resultsPerKeyword || userConfig.resultsPerKeyword || 35,
    keywordAllocations: ruleScrape.keywordAllocations || {},
    hotFeed: ruleScrape.hotFeed || {},
  });
  const result = await scraper.scrape(queries, customParams);
  console.log(`TikTok scrape complete. Filtered videos: ${result.length}`);
}

module.exports = { TikTokScraper, parseTokenPool, uniqueTokens };

if (require.main === module) {
  main().catch((error) => {
    console.error(`TikTok scrape failed: ${getErrorMessage(error)}`);
    process.exit(1);
  });
}
