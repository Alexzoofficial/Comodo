export async function onRequestPost(context) {
  const { request, env } = context;
  const data = await request.json();
  const { prompt } = data;

  const OPENROUTER_API_KEY = env.OPENROUTER_API_KEY;
  const SEARCH_API_KEY = env.SEARCH_API_KEY;
  const AI_MODEL = env.AI_MODEL || "qwen/qwen3-coder:free";

  let searchResults = "";
  const searchKeywords = ["search", "find", "latest", "current", "news", "who is", "weather", "today"];
  if (searchKeywords.some(kw => prompt.toLowerCase().includes(kw))) {
    try {
      const searchResp = await fetch("https://alexzo.vercel.app/api/search", {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${SEARCH_API_KEY}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ query: prompt })
      });
      if (searchResp.ok) {
        const res = await searchResp.json();
        searchResults = "\n\nWeb Search Results:\n" + JSON.stringify(res.results || res, null, 2);
      }
    } catch (e) {}
  }

  const messages = [
    { role: "system", content: `You are Comodo, an extremely skilled software engineer. You help users build projects. Provide code in ---FILE:filename--- content ---ENDFILE--- or ---DIFF:filename--- content ---ENDDIFF--- format.${searchResults}` },
    { role: "user", content: prompt }
  ];

  const response = await fetch("https://openrouter.ai/api/v1/chat/completions", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${OPENROUTER_API_KEY}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      model: AI_MODEL,
      messages: messages,
      stream: true
    })
  });

  const { readable, writable } = new TransformStream();
  const writer = writable.getWriter();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const encoder = new TextEncoder();

  (async () => {
    let partial = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      partial += decoder.decode(value, { stream: true });
      const lines = partial.split("\n");
      partial = lines.pop();

      for (const line of lines) {
        if (line.trim().startsWith("data: ")) {
          const dataStr = line.trim().slice(6);
          if (dataStr === "[DONE]") break;
          try {
            const json = JSON.parse(dataStr);
            const content = json.choices[0].delta.content;
            if (content) {
              await writer.write(encoder.encode(content));
            }
          } catch (e) {}
        }
      }
    }
    writer.close();
  })();

  return new Response(readable, {
    headers: { "Content-Type": "text/plain; charset=utf-8" }
  });
}
