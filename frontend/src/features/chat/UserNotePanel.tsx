import { useState } from 'react'
import type { RefObject } from 'react'
import { userNoteStore } from '../../services/userNoteStore.ts'
import type { UserNote } from '../../services/userNoteStore.ts'

// API 모드의 유저노트 화면. 이 브라우저에 저장된 기억을 보여 주고 모두 지울 수 있다.
const FIELD_LABELS: Record<string, string> = { nickname: '호칭', interest: '관심사', promise: '약속/응원', repeated_topic: '반복 주제', section_choice: '구간 선택' }
const IMPORTANCE_LABELS: Record<string, string> = { high: '중요', medium: '보통', low: '가벼움' }

export function UserNotePanel({ headingRef }: { headingRef?: RefObject<HTMLHeadingElement | null> }) {
  const [notes, setNotes] = useState<UserNote[]>(() => userNoteStore.read())
  function clear() { userNoteStore.clear(); setNotes([]) }
  return <>
    <p className="eyebrow">USER NOTE</p>
    <h2 ref={headingRef} tabIndex={-1}>유저노트</h2>
    <div className="record-empty note-sheet">
      <div className="note-sheet-header"><span>푸르마가 기억하는 것</span><span aria-hidden="true">✎</span></div>
      {notes.length === 0 ? <div className="note-empty-content"><span className="note-status">아직 기록 없음</span><p>대화에서 알려 준 호칭이나 관심사가 여기에 쌓여요.</p></div>
        : <ul aria-label="저장된 기억" style={{ listStyle: 'none', margin: 0, padding: 0, textAlign: 'left' }}>{notes.map(note => <li key={note.key}><b>{FIELD_LABELS[note.field] ?? note.field}</b> · {note.value} <small>({IMPORTANCE_LABELS[note.importance] ?? note.importance})</small></li>)}</ul>}
      {notes.length > 0 && <button type="button" className="restart" onClick={clear}>기억 모두 지우기</button>}
    </div>
    <p className="demo-note">기억은 이 브라우저에만 저장돼요 · 대화 때마다 서버로 보내 쓰고, 지우면 다음 대화부터 빈 기억을 보내요.</p>
  </>
}
