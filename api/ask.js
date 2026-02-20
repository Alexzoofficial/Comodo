const { state } = require('./_store');

const OPENROUTER_API_URL = 'https://openrouter.ai/api/v1/chat/completions';
const OPENROUTER_MODEL = 'qwen/qwen3-coder:free';
const OPENROUTER_API_KEY = process.env.OPENROUTER_API_KEY || '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';
const ALEXZO_SEARCH_API_URL = 'https://alexzo.vercel.app/api/search';
const ALEXZO_SEARCH_API_KEY = process.env.ALEXZO_SEARCH_API_KEY || 'alexzo_d6ld7tundbcpi5bklna74n';

function shouldUseWebSearch(prompt) {
  if (!prompt) return false;
  return /\b(latest|today|current|news|recent|update|trend|trending|price|market|release date|advancement|advancements|what is happening)\b/i.test(prompt);
}

async function fetchWebSearchContext(query) {
  if (!ALEXZO_SEARCH_API_KEY) return '';
  try {
    const resp = await fetch(ALEXZO_SEARCH_API_URL, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${ALEXZO_SEARCH_API_KEY}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ query })
    });
    if (!resp.ok) return '';
    const data = await resp.json();
    return JSON.stringify(data).slice(0, 3500);
  } catch {
    return '';
  }
}

module.exports = async (req, res) => {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });
  const body = req.body || {};
  const prompt = body.prompt || '';
  const chatId = body.chat_id;

  if (!chatId) return res.status(400).json({ error: 'No Project ID' });
  if (!state.chats[chatId]) return res.status(404).json({ error: 'Project not found' });
  if (!OPENROUTER_API_KEY) return res.status(500).send('Configuration error: Missing OPENROUTER_API_KEY.');

  const chat = state.chats[chatId];
  const messages = chat.messages || [];
  const history = messages.slice(-6).map((m) => `${m.role}: ${(m.content || '').slice(0, 200)}`).join('\n');

  let webContext = '';
  if (shouldUseWebSearch(prompt)) {
    const searchData = await fetchWebSearchContext(prompt);
    if (searchData) webContext = `\n\nWeb search context (fresh internet data):\n${searchData}`;
  }

  const upstream = await fetch(OPENROUTER_API_URL, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${OPENROUTER_API_KEY}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      model: OPENROUTER_MODEL,
      stream: true,
      messages: [
        {
          role: 'system',
          content: 'You are a coding assistant. Reply with clean, helpful code and explanations. Use web context only when provided.'
        },
        {
          role: 'user',
          content: `Conversation history:\n${history}\n\nCurrent user request:\n${prompt}${webContext}`
        }
      ]
    })
  });

  if (!upstream.ok || !upstream.body) {
    const errText = await upstream.text();
    return res.status(upstream.status || 500).send(`API Error: ${upstream.status} - ${errText.slice(0, 300)}`);
  }

  res.setHeader('Content-Type', 'text/plain; charset=utf-8');
  res.setHeader('Cache-Control', 'no-cache');

  let fullReply = '';
  const reader = upstream.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (!line.startsWith('data:')) continue;
      const payloadText = line.slice(5).trim();
      if (payloadText === '[DONE]') continue;
      try {
        const payload = JSON.parse(payloadText);
        const chunk = payload?.choices?.[0]?.delta?.content || '';
        if (chunk) {
          fullReply += chunk;
          res.write(chunk);
        }
      } catch {
        // ignore malformed chunks
      }
    }
  }

  state.chats[chatId].messages.push({ role: 'user', content: prompt });
  state.chats[chatId].messages.push({ role: 'assistant', content: fullReply });
  res.end();
};
