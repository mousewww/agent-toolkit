# Skill: Router

## 用途
最外层路由。拿到用户原话后，判断它该走哪条处理路径：

- **programming** → 进入编程代理管线（intake → refine → prompt_optimize → dispatch → ...）
- **search** → 直接联网搜索并生成回答
- **chat** → 直接由轻量模型回答
- **tool** → 调用特定工具（如发邮件、查日历、创建待办）

## 为什么放在最外层

很多请求根本不是编程任务（查天气、问新闻、闲聊）。如果让它们走完整编程管线，会白白消耗 intake/refine/prompt_optimize 三次模型调用。最外层路由只需一次 v4-flash 调用即可分流，最快最省。

## 输入

```json
{
  "raw": "用户原话"
}
```

## 输出

```json
{
  "route": "programming | search | chat | tool",
  "confidence": 0.95,
  "reason": "分类理由",
  "response": "search/chat 类型时的直接回答",
  "next": "programming/tool 类型时建议下一步",
  "parameters": {
    "search_query": "搜索关键词",
    "tool_name": "工具名"
  }
}
```

## 路由规则

| 类型 | 说明 | 下一步 |
|------|------|--------|
| `programming` | 改代码、建文件、跑脚本、处理项目 | 进入 `pipeline/runner.py` |
| `search` | 查天气、新闻、股价、当前事件 | 调用 DuckDuckGo 搜索 + v4-flash 总结 |
| `chat` | 闲聊、解释概念、头脑风暴 | v4-flash 直接回答 |
| `tool` | 发邮件、查日历、创建待办 | 调用对应工具（待扩展） |

## 联网搜索

默认使用 **DuckDuckGo Instant Answer API**：

- 免费、无需 API key
- 适合简单事实查询
- 结果有限，复杂搜索可后续替换为 Bing/Serper/Brave 等

搜索失败时，会 fallback 到模型基于自身知识回答，并标注可能不是最新信息。

## 环境变量

```bash
ROUTER_API_KEY=sk-xxx            # 默认读取 OPENAI_API_KEY
ROUTER_BASE_URL=https://api.deepseek.com/v1
ROUTER_MODEL=deepseek-v4-flash   # 可覆盖
```

## 用法

```bash
# 直接传字符串
python agent-toolkit/pipeline/router.py --raw "今天北京天气怎样"

# 从文件读取
python agent-toolkit/pipeline/router.py --file input.txt

# 结合编程管线
python agent-toolkit/pipeline/router.py --file input.txt | \
  python -c "import json,sys,subprocess; d=json.load(sys.stdin); \
    subprocess.run([sys.executable, d['next'], '--file', 'input.txt']) if d['route']=='programming' else print(d['response'])"
```
