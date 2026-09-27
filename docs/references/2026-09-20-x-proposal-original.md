# Media@Missher X/Twitter 采集方案

> 版本：v1.0 | 日期：2026-09-20 | 作者：Hermes Agent

---

## 一、可行性验证结果

通过 Chrome CDP + X GraphQL API 监听，已成功抓取 24 条推文数据。

**技术路径**：
- 连接现有 Chrome（127.0.0.1:9222）
- 打开 `x.com/search?q=关键词`
- 监听 `x.com/i/api/graphql` 响应
- 解析 `SearchTimeline` 接口返回的推文数据

---

## 二、可抓取字段（完整）

### 2.1 推文基本信息

| 字段 | API路径 | 示例 | 备注 |
|------|---------|------|------|
| 推文ID | `rest_id` | 2094027198273368295 | 唯一标识 |
| 发布时间 | `legacy.created_at` | Sun Aug 30 11:39:23 +0000 2026 | 原始时间字符串 |
| 内容文本 | `legacy.full_text` | 完整推文内容 | 含换行、链接 |
| 语言 | `legacy.lang` | zh / en / ja | 自动检测 |
| 推文链接 | 拼接 | `https://x.com/{screen_name}/status/{rest_id}` | 自构建 |

### 2.2 互动数据（6维）

| 字段 | API路径 | 示例 | 对比微博 |
|------|---------|------|----------|
| 点赞数 | `legacy.favorite_count` | 8,363 | ✅ 有 |
| 转发数 | `legacy.retweet_count` | 404 | ✅ 有 |
| 回复数 | `legacy.reply_count` | 6 | ✅ 有 |
| 引用数 | `legacy.quote_count` | 2 | ❌ 微博无 |
| 浏览量 | `views.count` | 415,822 | ❌ 微博无 |
| 书签数 | `bookmark_count` | - | ❌ 微博无 |

**X 比微博多 3 个维度**：引用数、浏览量、书签数

### 2.3 用户信息（完整资料）

| 字段 | API路径 | 示例 | 对比微博 |
|------|---------|------|----------|
| 用户名 | `result.core.screen_name` | SimonaConr93747 | ✅ 有 |
| 显示名 | `result.core.name` | Simona Conrad | ✅ 有 |
| 用户ID | `result.rest_id` | 2040009202018504704 | ✅ 有 |
| 粉丝数 | `result.relationship_counts.followers` | 2,440 | ✅ 有 |
| 关注数 | `result.relationship_counts.following` | 4 | ✅ 有 |
| 头像URL | `result.avatar.image_url` | https://pbs.twimg.com/... | ✅ 有 |
| 简介 | `result.profile_bio.description` | 个人简介文本 | ✅ 有 |
| 认证状态 | `result.verification.verified` | false | ✅ 有 |
| 蓝标认证 | `result.is_blue_verified` | false | ❌ 微博无 |
| 注册时间 | `result.core.created_at` | Fri Apr 03 2026 | ✅ 有 |
| 推文总数 | `result.tweet_counts.tweets` | 37 | ✅ 有 |
| 媒体推文数 | `result.tweet_counts.media_tweets` | 33 | ❌ 微博无 |
| 位置 | `result.location.location` | Guangzhou | ✅ 有 |
| 网站 | `result.website.url` | https://... | ✅ 有 |
| 私密账号 | `result.privacy.protected` | false | ✅ 有 |

**X 比微博多 2 个维度**：蓝标认证、媒体推文数

### 2.4 媒体内容

| 字段 | API路径 | 示例 | 备注 |
|------|---------|------|------|
| 媒体类型 | `extended_entities.media[].type` | video / photo / animated_gif | 枚举值 |
| 媒体URL | `extended_entities.media[].media_url_https` | https://pbs.twimg.com/... | 原始媒体链接 |
| 视频时长 | `extended_entities.media[].video_info.duration_millis` | 30000 | 毫秒 |
| 视频分辨率 | `video_info.variants[].content_type` | video/mp4 | 多分辨率可选 |
| 缩略图 | `media[].sizes.thumb` | 多尺寸 | 150x150 等 |

### 2.5 链接与话题

| 字段 | API路径 | 示例 | 备注 |
|------|---------|------|------|
| 外部链接 | `entities.urls[].expanded_url` | https://... | 推文中的链接 |
| 话题标签 | `entities.hashtags[].text` | 萤火虫漫展 | 不含#号 |
| @提及 | `entities.user_mentions[].screen_name` | FireFlyACG | 被@的用户 |
| 会话ID | `conversation_id_str` | 2094027198273368295 | 对话线程 |
| 回复对象 | `in_reply_to_screen_name` | 用户名 | 如果是回复 |

---

## 三、与现有四平台对比

| 维度 | B站 | 小红书 | 抖音 | 微博 | **X** |
|------|-----|--------|------|------|-------|
| 点赞 | ✅ | ✅ | ✅ | ✅ | ✅ |
| 评论 | ✅ | ⚠️风控 | ✅ | ✅ | ✅ |
| 转发/分享 | ✅ | ⚠️风控 | ✅ | ✅ | ✅ |
| 收藏 | ✅ | ⚠️风控 | ✅ | N/A | ✅ |
| 引用 | N/A | N/A | N/A | N/A | **✅** |
| 浏览量 | ✅(play) | N/A | ✅(plays) | N/A | **✅** |
| 书签 | N/A | N/A | N/A | N/A | **✅** |
| 蓝标认证 | N/A | N/A | N/A | N/A | **✅** |
| 媒体推文数 | N/A | N/A | N/A | N/A | **✅** |

**X 是互动维度最丰富的平台**（9维 vs 微博5维）

---

## 四、采集模式设计

### 4.1 搜索模式（keyword search）

```bash
python3 scrape_x.py --search "萤火虫漫展" --count 50
```

- 打开 `x.com/search?q=关键词&f=top`
- 监听 SearchTimeline API
- 滚动加载更多（每次 20 条）
- 去重后保存

### 4.2 用户模式（user timeline）

```bash
python3 scrape_x.py --user "FireFlyACG" --count 30
```

- 打开 `x.com/{username}`
- 监听 UserTweets API
- 滚动加载更多

### 4.3 话题模式（hashtag）

```bash
python3 scrape_x.py --hashtag "萤火虫漫展" --count 50
```

- 打开 `x.com/hashtag/话题名`
- 监听 HashtagTimeline API

---

## 五、输出字段设计

```json
{
  "platform": "x",
  "type": "tweet",
  "tweet_id": "2094027198273368295",
  "link": "https://x.com/SimonaConr93747/status/2094027198273368295",
  "text": "完整推文内容...",
  "lang": "zh",
  "created_at": "Sun Aug 30 11:39:23 +0000 2026",
  "published_at": "2026-08-30T11:39:23Z",
  
  "liked": 8363,
  "comments": 6,
  "shares": 404,
  "quotes": 2,
  "views": 415822,
  "bookmarks": null,
  
  "author": "Simona Conrad",
  "author_id": "2040009202018504704",
  "author_link": "https://x.com/SimonaConr93747",
  "screen_name": "SimonaConr93747",
  "followers_count": 2440,
  "following_count": 4,
  "tweets_count": 37,
  "verified": false,
  "blue_verified": false,
  "avatar": "https://pbs.twimg.com/profile_images/...",
  "bio": "",
  "location": "",
  "website": "",
  "joined_at": "Fri Apr 03 10:11:11 +0000 2026",
  
  "media": [
    {
      "type": "video",
      "url": "https://pbs.twimg.com/...",
      "duration_ms": 30000,
      "thumbnail": "https://pbs.twimg.com/..."
    }
  ],
  "urls": ["https://mypikpak.com/..."],
  "hashtags": ["绿帽", "黄豆魔改"],
  "mentions": ["FireFlyACG"],
  
  "conversation_id": "2094027198273368295",
  "in_reply_to": null,
  "search_keyword": "萤火虫漫展",
  "observed_at": "2026-09-20T13:34:00+08:00"
}
```

---

## 六、技术实现

### 6.1 核心逻辑

```python
async def scrape_x(ctx, keyword, max_items=50):
    page = await ctx.new_page()
    tweets = []
    seen_ids = set()
    
    async def handle_response(response):
        if 'x.com/i/api/graphql' in response.url:
            data = await response.json()
            extract_tweets(data, tweets, seen_ids)
    
    page.on('response', handle_response)
    await page.goto(f'https://x.com/search?q={keyword}&f=top')
    
    # 滚动加载
    while len(tweets) < max_items:
        await page.mouse.wheel(0, 2000)
        await page.wait_for_timeout(2000)
    
    await page.close()
    return tweets
```

### 6.2 用户信息提取（新 API 结构）

```python
def extract_user_info(tweet):
    result = tweet.get('core', {}).get('user_results', {}).get('result', {})
    return {
        'screen_name': result.get('core', {}).get('screen_name'),
        'name': result.get('core', {}).get('name'),
        'user_id': result.get('rest_id'),
        'followers': result.get('relationship_counts', {}).get('followers'),
        'following': result.get('relationship_counts', {}).get('following'),
        'avatar': result.get('avatar', {}).get('image_url'),
        'bio': result.get('profile_bio', {}).get('description'),
        'verified': result.get('verification', {}).get('verified'),
        'blue_verified': result.get('is_blue_verified'),
        'joined_at': result.get('core', {}).get('created_at'),
        'tweets_count': result.get('tweet_counts', {}).get('tweets'),
        'media_tweets': result.get('tweet_counts', {}).get('media_tweets'),
        'location': result.get('location', {}).get('location'),
        'website': result.get('website', {}).get('url'),
    }
```

### 6.3 风控处理

- X 对 CDP 检测较弱（相比小红书）
- 每次滚动间隔 2-3 秒
- 连续搜索 100 条后暂停 30 秒
- 遇到 "Something went wrong" 停止采集

---

## 七、集成计划

### 7.1 文件结构

```
Media@Missher/
├── media-missher/
│   └── scripts/
│       ├── scrape_x.py          # 新增
│       ├── scrape_weibo.py      # 现有
│       ├── scrape_bilibili.py   # 现有
│       ├── scrape_xhs.py        # 现有
│       └── scrape_douyin.py     # 现有
```

### 7.2 run_collection.py 集成

```bash
# 搜索模式
python3 run_collection.py --platform x --search "萤火虫漫展" --count 50

# 用户模式
python3 run_collection.py --platform x --x-uid "FireFlyACG" --count 30

# 混合模式
python3 run_collection.py --platform x,weibo --search "萤火虫漫展" --count 30
```

### 7.3 平台字段映射

| Media@Missher 标准字段 | X 字段 |
|------------------------|--------|
| `liked` | `favorite_count` |
| `comments` | `reply_count` |
| `shares` | `retweet_count` |
| `collected` | `bookmark_count` |
| `author` | `core.name` |
| `author_id` | `rest_id` |
| `author_link` | 拼接 |
| `link` | 拼接 |
| `title` | `full_text` |
| `date` | `created_at` |

---

## 八、注意事项

1. **登录态**：需要 Chrome 已登录 X
2. **API 变化**：X 的 GraphQL API 可能变化，需要维护
3. **速率限制**：X 对搜索有速率限制，大量采集需控制频率
4. **隐私合规**：采集公开推文合规，但不应采集私密账号

---

## 九、预估开发时间

| 阶段 | 内容 | 时间 |
|------|------|------|
| 核心脚本 | scrape_x.py | 2小时 |
| 集成测试 | run_collection.py 适配 | 1小时 |
| 风控优化 | 滚动策略、错误处理 | 1小时 |
| 文档更新 | SKILL.md 更新 | 0.5小时 |
| **总计** | | **4.5小时** |

---

## 十、下一步

1. ✅ 可行性验证（已完成）
2. ⬜ 编写 scrape_x.py 脚本
3. ⬜ 集成到 run_collection.py
4. ⬜ 实测 50 条推文采集
5. ⬜ 更新 SKILL.md 文档

---

*方案完成，等待老大审核 🎀*
