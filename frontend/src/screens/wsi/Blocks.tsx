import type { Block } from '@/api/wsi';
import { Button, TextArea } from '@/components/ui';
import { policyHelp as H } from '@/help/wsi';
import './wsi.css';

/** A policy's text: headings, paragraphs and lists only (rendered as text, never as HTML). */
export function BlockView({ blocks }: { blocks: Block[] }) {
  return (
    <>
      {blocks.map((b, i) => {
        if (b.type === 'heading') { const Tag = (b.level === 1 ? 'h1' : b.level === 2 ? 'h2' : 'h3') as 'h1'; return <Tag key={i}>{b.text}</Tag>; }
        if (b.type === 'paragraph') return <p key={i}>{b.text}</p>;
        const L = b.ordered ? 'ol' : 'ul';
        return <L key={i}>{b.items.map((t, j) => <li key={j}>{t}</li>)}</L>;
      })}
    </>
  );
}

const KINDS = [
  { value: 'h1', label: 'Title' }, { value: 'h2', label: 'Heading' }, { value: 'h3', label: 'Subheading' },
  { value: 'p', label: 'Paragraph' }, { value: 'ul', label: 'Bulleted list' }, { value: 'ol', label: 'Numbered list' },
];

function kindOf(b: Block): string {
  if (b.type === 'heading') return `h${b.level}`;
  if (b.type === 'paragraph') return 'p';
  return b.ordered ? 'ol' : 'ul';
}

function textOf(b: Block): string {
  return b.type === 'list' ? b.items.join('\n') : b.text;
}

function make(kind: string, text: string): Block {
  if (kind.startsWith('h')) return { type: 'heading', level: Number(kind[1]) as 1 | 2 | 3, text: text.replace(/\s*\n\s*/g, ' ') };
  if (kind === 'p') return { type: 'paragraph', text: text.replace(/\s*\n\s*/g, ' ') };
  return { type: 'list', ordered: kind === 'ol', items: text.split('\n') };
}

/** The editor: each block has a type and its text; lists take one item per line. */
export function BlockEditor({ blocks, onChange }: { blocks: Block[]; onChange: (b: Block[]) => void }) {
  const set = (i: number, b: Block) => onChange(blocks.map((x, j) => (j === i ? b : x)));
  const move = (i: number, d: number) => { const n = [...blocks]; const [b] = n.splice(i, 1); n.splice(i + d, 0, b); onChange(n); };
  return (
    <div className="stack-sm">
      {blocks.map((b, i) => {
        const kind = kindOf(b);
        const label = `${KINDS.find((k) => k.value === kind)?.label} ${i + 1}`;
        return (
          <div key={i} className="wsi-block" role="group" aria-label={label}>
            <div className="wsi-block-tools">
              <select aria-label={`Type of block ${i + 1}`} value={kind} onChange={(e) => set(i, make(e.target.value, textOf(b)))} title={H.blockType}>
                {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
              </select>
              <Button size="sm" variant="ghost" disabled={i === 0} onClick={() => move(i, -1)} aria-label={`Move block ${i + 1} up`}>Up</Button>
              <Button size="sm" variant="ghost" disabled={i === blocks.length - 1} onClick={() => move(i, 1)} aria-label={`Move block ${i + 1} down`}>Down</Button>
              <Button size="sm" variant="ghost" onClick={() => onChange([...blocks.slice(0, i + 1), { type: 'paragraph', text: '' }, ...blocks.slice(i + 1)])} aria-label={`Add a paragraph after block ${i + 1}`}>Add after</Button>
              <Button size="sm" variant="ghost" onClick={() => onChange(blocks.filter((_, j) => j !== i))} aria-label={`Remove block ${i + 1}`}>Remove</Button>
            </div>
            <TextArea label={<span className="sr-only">{label}</span>} hint={b.type === 'list' ? H.blockText : undefined} rows={b.type === 'heading' ? 1 : Math.min(10, Math.max(2, Math.ceil(textOf(b).length / 90) + (b.type === 'list' ? b.items.length : 0)))}
              value={textOf(b)} onChange={(e) => set(i, make(kind, e.target.value))} />
          </div>
        );
      })}
      <div><Button size="sm" onClick={() => onChange([...blocks, { type: 'paragraph', text: '' }])}>Add paragraph</Button></div>
    </div>
  );
}
