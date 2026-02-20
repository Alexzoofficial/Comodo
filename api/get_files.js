const { state, ensureChat } = require('./_store');

module.exports = (req, res) => {
  const chatId = req.query.chat_id;
  if (!chatId) return res.status(400).json({ error: 'Missing chat_id' });
  ensureChat(chatId);
  res.status(200).json(state.filesByChat[chatId]);
};
