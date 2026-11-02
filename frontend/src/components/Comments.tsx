import { useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '@/api/client';
import { useMe } from '@/api/auth';
import { commentsKey, useComments, type CommentItem, type CommentObjectType, type Mentionable } from '@/api/wsl';
import { Alert, Badge, Button, Dialog, fmtDateTime } from '@/components/ui';
import { commentHelp as H } from '@/help/wsl';
import './comments.css';

type Props = { objectType: CommentObjectType; objectId: string; title?: string };

/** Threaded comments on an audit object (spec §21 F18). Futran comments are internal unless shared; client comments are
 *  always shared; comments on a finding that is not approved stay internal. Type @ to mention someone. */
export function Comments({ objectType, objectId, title = 'Comments' }: Props) {
  const q = useComments(objectType, objectId);
  const { data: me } = useMe();
  const [withdrawing, setWithdrawing] = useState<CommentItem | null>(null);
  const [replyTo, setReplyTo] = useState<string | null>(null);
  if (q.isLoading) return <section className="cmt" aria-label={title}><p className="small muted">Loading comments…</p></section>;
  if (!q.data) return <section className="cmt" aria-label={title}><Alert tone="danger">{errorMessage(q.error)}</Alert></section>;
  const d = q.data;
  const count = d.threads.reduce((n, t) => n + 1 + t.replies.length, 0);
  return (
    <section className="cmt" aria-label={title}>
      <h3 className="cmt-h">{title} <span className="muted small">({count})</span></h3>
      {d.threads.length === 0 && <p className="small muted" style={{ margin: 0 }}>No comments yet.</p>}
      <ul className="cmt-list">
        {d.threads.map((t) => (
          <li key={t.id} className="cmt-thread">
            <CommentView c={t} objectType={objectType} objectId={objectId} onWithdraw={setWithdrawing} />
            {t.replies.length > 0 && (
              <ul className="cmt-replies">
                {t.replies.map((r) => <li key={r.id}><CommentView c={r} objectType={objectType} objectId={objectId} onWithdraw={setWithdrawing} /></li>)}
              </ul>
            )}
            {replyTo === t.id
              ? <Composer objectType={objectType} objectId={objectId} parentId={t.id} visibility={t.visibility} options={[t.visibility]} onDone={() => setReplyTo(null)} reply />
              : <button type="button" className="linklike small cmt-reply" onClick={() => setReplyTo(t.id)}>Reply</button>}
          </li>
        ))}
      </ul>
      <Composer objectType={objectType} objectId={objectId} visibility={d.default_visibility} options={d.visibility_options} isClient={me?.organization.type !== 'futran'}
        draftOnly={me?.organization.type === 'futran' && !d.shared_allowed} />
      {withdrawing && <WithdrawDialog c={withdrawing} objectType={objectType} objectId={objectId} onClose={() => setWithdrawing(null)} />}
    </section>
  );
}

/** "Comments (n)" button that opens the thread in place, for rows in lists. */
export function CommentsToggle({ objectType, objectId, count, label, defaultOpen = false }: Props & { count?: number; label?: string; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="cmt-toggle">
      <button type="button" className="linklike small" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? 'Hide comments' : `Comments${count ? ` (${count})` : ''}`}{label ? <span className="sr-only"> on {label}</span> : null}
      </button>
      {open && <Comments objectType={objectType} objectId={objectId} />}
    </div>
  );
}

function renderBody(c: CommentItem) {
  if (c.body == null) return <em className="muted">Comment withdrawn.</em>;
  const names = c.mentions.map((m) => m.name).filter(Boolean) as string[];
  if (!names.length) return c.body;
  const re = new RegExp(`(@(?:${names.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')}))`, 'g');
  return c.body.split(re).map((part, i) => (part.startsWith('@') && names.includes(part.slice(1)) ? <strong key={i} className="cmt-mention">{part}</strong> : part));
}

function CommentView({ c, objectType, objectId, onWithdraw }: { c: CommentItem; objectType: CommentObjectType; objectId: string; onWithdraw: (c: CommentItem) => void }) {
  const [editing, setEditing] = useState(false);
  return (
    <article className={`cmt-item ${c.visibility === 'internal' ? 'cmt-internal' : ''}`} aria-label={`Comment by ${c.author ?? 'someone'}`}>
      <div className="cmt-meta">
        <strong>{c.author}</strong>
        <Badge tone={c.author_side === 'futran' ? 'navy' : 'default'}>{c.author_side === 'futran' ? 'Futran' : 'Client'}</Badge>
        <Badge tone={c.visibility === 'internal' ? 'warn' : 'success'}>{c.visibility === 'internal' ? 'Internal' : 'Shared'}</Badge>
        <span className="small muted">{fmtDateTime(c.at)}{c.edited_at ? ' · edited' : ''}{c.withdrawn ? ` · withdrawn ${fmtDateTime(c.withdrawn_at)}` : ''}</span>
      </div>
      {editing
        ? <EditBox c={c} objectType={objectType} objectId={objectId} onDone={() => setEditing(false)} />
        : <p className="cmt-body">{renderBody(c)}</p>}
      {!editing && (c.can_edit || c.can_withdraw) && (
        <div className="row cmt-actions">
          {c.can_edit && <button type="button" className="linklike small" onClick={() => setEditing(true)}>Edit</button>}
          {c.can_withdraw && <button type="button" className="linklike small" onClick={() => onWithdraw(c)}>Withdraw</button>}
        </div>
      )}
    </article>
  );
}

function useMentionable(objectType: CommentObjectType, objectId: string, visibility: string) {
  return useQuery({
    queryKey: ['mentionable', objectType, objectId, visibility],
    queryFn: () => api.get<{ people: Mentionable[] }>(`/comments/mentionable?object_type=${objectType}&object_id=${encodeURIComponent(objectId)}&visibility=${visibility}`),
    staleTime: 60_000,
  });
}

/** The textarea with @mention suggestions. Returns the ids of people still named in the text. */
function MentionInput({ value, onChange, people, label, id }: { value: string; onChange: (v: string, ids: string[]) => void; people: Mentionable[]; label: string; id: string }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [query, setQuery] = useState<string | null>(null);
  const [active, setActive] = useState(0);
  const picked = useRef<Map<string, string>>(new Map());
  const hits = useMemo(() => (query == null ? [] : people.filter((p) => p.name.toLowerCase().includes(query.toLowerCase())).slice(0, 6)), [people, query]);
  const ids = (text: string) => [...picked.current.entries()].filter(([name]) => text.includes(`@${name}`)).map(([, pid]) => pid);
  function update(text: string) {
    const el = ref.current;
    const upto = text.slice(0, el?.selectionStart ?? text.length);
    const m = /(?:^|\s)@([\p{L}' .-]{0,30})$/u.exec(upto);
    setQuery(m ? m[1] : null);
    setActive(0);
    onChange(text, ids(text));
  }
  function pick(p: Mentionable) {
    const el = ref.current;
    const pos = el?.selectionStart ?? value.length;
    const before = value.slice(0, pos).replace(/@[\p{L}' .-]{0,30}$/u, `@${p.name} `);
    const text = before + value.slice(pos);
    picked.current.set(p.name, p.id);
    setQuery(null);
    onChange(text, ids(text));
    requestAnimationFrame(() => { el?.focus(); el?.setSelectionRange(before.length, before.length); });
  }
  function key(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (!hits.length) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((active + 1) % hits.length); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((active - 1 + hits.length) % hits.length); }
    else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); pick(hits[active]); }
    else if (e.key === 'Escape') setQuery(null);
  }
  return (
    <div className="cmt-input">
      <label htmlFor={id} className="sr-only">{label}</label>
      <textarea id={id} ref={ref} rows={3} value={value} onChange={(e) => update(e.target.value)} onKeyDown={key} placeholder="Write a comment. Type @ to mention someone."
        aria-describedby={`${id}-help`} aria-autocomplete="list" aria-controls={hits.length ? `${id}-list` : undefined} aria-expanded={hits.length > 0} role="combobox" />
      {hits.length > 0 && (
        <ul className="cmt-suggest" id={`${id}-list`} role="listbox" aria-label="People you can mention">
          {hits.map((p, i) => (
            <li key={p.id} role="option" aria-selected={i === active} className={i === active ? 'active' : ''} onMouseDown={(e) => { e.preventDefault(); pick(p); }}>
              <strong>{p.name}</strong> <span className="small muted">{p.side === 'futran' ? 'Futran' : 'Client'}{p.job_title ? ` · ${p.job_title}` : ''}</span>
            </li>
          ))}
        </ul>
      )}
      <p id={`${id}-help`} className="small muted cmt-help">{H.body}</p>
    </div>
  );
}

function Composer({ objectType, objectId, parentId, visibility: initial, options, onDone, reply, isClient, draftOnly }: {
  objectType: CommentObjectType; objectId: string; parentId?: string; visibility: 'internal' | 'shared'; options: ('internal' | 'shared')[]; onDone?: () => void; reply?: boolean; isClient?: boolean; draftOnly?: boolean;
}) {
  const qc = useQueryClient();
  const [text, setText] = useState('');
  const [mentions, setMentions] = useState<string[]>([]);
  const [visibility, setVisibility] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const people = useMentionable(objectType, objectId, visibility);
  const fid = `cmt-${objectType}-${objectId}-${parentId ?? 'new'}`;
  async function submit() {
    if (busy || !text.trim()) return;
    setBusy(true); setErr(null);
    try {
      await api.post('/comments', { object_type: objectType, object_id: objectId, body: text, visibility, parent_id: parentId ?? null, mention_ids: mentions });
      setText(''); setMentions([]);
      await qc.invalidateQueries({ queryKey: commentsKey(objectType, objectId) });
      await qc.invalidateQueries({ queryKey: ['comment-counts', objectType] });
      onDone?.();
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <form className={`cmt-composer ${reply ? 'cmt-composer-reply' : ''}`} onSubmit={(e) => { e.preventDefault(); void submit(); }}>
      <MentionInput id={fid} label={reply ? 'Reply' : 'New comment'} value={text} people={people.data?.people ?? []} onChange={(v, ids) => { setText(v); setMentions(ids); }} />
      {!reply && options.length > 1 && (
        <fieldset className="cmt-vis">
          <legend className="small">Who can see it</legend>
          <label><input type="radio" name={`${fid}-vis`} checked={visibility === 'internal'} onChange={() => setVisibility('internal')} /> Internal (Futran only)</label>
          <label><input type="radio" name={`${fid}-vis`} checked={visibility === 'shared'} onChange={() => setVisibility('shared')} /> Shared with the client</label>
          <span className="small muted">{H.visibility}</span>
        </fieldset>
      )}
      {!reply && draftOnly && <p className="small muted" style={{ margin: 0 }}>{H.draftOnly}</p>}
      {!reply && isClient && <p className="small muted" style={{ margin: 0 }}>{H.clientNote}</p>}
      {err && <Alert tone="danger">{err}</Alert>}
      <div className="row">
        <Button type="submit" variant="primary" size="sm" disabled={busy || !text.trim()}>{busy ? 'Posting…' : reply ? 'Reply' : 'Post comment'}</Button>
        {onDone && <Button type="button" size="sm" onClick={onDone}>Cancel</Button>}
      </div>
    </form>
  );
}

function EditBox({ c, objectType, objectId, onDone }: { c: CommentItem; objectType: CommentObjectType; objectId: string; onDone: () => void }) {
  const qc = useQueryClient();
  const [text, setText] = useState(c.body ?? '');
  const [mentions, setMentions] = useState(c.mentions.map((m) => m.id));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const people = useMentionable(objectType, objectId, c.visibility);
  async function save() {
    if (busy) return;
    setBusy(true); setErr(null);
    try {
      await api.patch(`/comments/${c.id}`, { body: text, mention_ids: mentions });
      await qc.invalidateQueries({ queryKey: commentsKey(objectType, objectId) });
      onDone();
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <div className="stack-sm">
      <MentionInput id={`cmt-edit-${c.id}`} label="Edit comment" value={text} people={people.data?.people ?? []} onChange={(v, ids) => { setText(v); setMentions((prev) => [...new Set([...prev.filter((p) => c.mentions.some((m) => m.id === p && v.includes(`@${m.name}`))), ...ids])]); }} />
      <p className="small muted" style={{ margin: 0 }}>{H.edit}</p>
      {err && <Alert tone="danger">{err}</Alert>}
      <div className="row"><Button size="sm" variant="primary" disabled={busy || !text.trim()} onClick={save}>{busy ? 'Saving…' : 'Save'}</Button><Button size="sm" onClick={onDone}>Cancel</Button></div>
    </div>
  );
}

function WithdrawDialog({ c, objectType, objectId, onClose }: { c: CommentItem; objectType: CommentObjectType; objectId: string; onClose: () => void }) {
  const qc = useQueryClient();
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function go() {
    if (busy) return;
    setBusy(true); setErr(null);
    try {
      await api.post(`/comments/${c.id}/withdraw`, { reason });
      await qc.invalidateQueries({ queryKey: commentsKey(objectType, objectId) });
      onClose();
    } catch (e) { setErr(errorMessage(e)); setBusy(false); }
  }
  return (
    <Dialog title="Withdraw this comment?" onClose={onClose}>
      <div className="stack">
        <p style={{ margin: 0 }}>{H.withdraw}</p>
        <label className="field"><span className="label">Reason (optional)</span><input className="input" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} /></label>
        {err && <Alert tone="danger">{err}</Alert>}
        <div className="row"><Button variant="danger" disabled={busy} onClick={go}>{busy ? 'Withdrawing…' : 'Withdraw'}</Button><Button onClick={onClose}>Cancel</Button></div>
      </div>
    </Dialog>
  );
}
