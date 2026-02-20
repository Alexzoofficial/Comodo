const { state, ensureChat } = require('./_store');

module.exports = (req, res) => {
  const body = req.body || {};
  if (!body.chat_id || !body.path) return res.status(400).json({ error: 'Missing data' });
  ensureChat(body.chat_id);
  state.foldersByChat[body.chat_id].add(body.path);
  res.status(200).json({ success: true });
};
