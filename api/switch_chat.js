const { state } = require('./_store');

module.exports = (req, res) => {
  const id = req.query.id;
  if (id && state.chats[id]) state.current_chat = id;
  res.status(200).json({ success: true });
};
