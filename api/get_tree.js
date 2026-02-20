const { fileTree } = require('./_store');

module.exports = (req, res) => {
  const chatId = req.query.chat_id;
  if (!chatId) return res.status(400).json({ error: 'Missing chat_id' });
  res.status(200).json(fileTree(chatId));
};
