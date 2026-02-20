const { state, ensureChat } = require('./_store');

module.exports = (req, res) => {
  const body = req.body || {};
  if (!body.chat_id || !body.filename) return res.status(400).json({ error: 'Missing data' });
  ensureChat(body.chat_id);
  state.filesByChat[body.chat_id][body.filename] = body.content || '';
  const parts = body.filename.split('/');
  if (parts.length > 1) {
    let acc = '';
    for (let i = 0; i < parts.length - 1; i += 1) {
      acc = acc ? `${acc}/${parts[i]}` : parts[i];
      state.foldersByChat[body.chat_id].add(acc);
    }
  }
  res.status(200).json({ added: 1, removed: 0 });
};
