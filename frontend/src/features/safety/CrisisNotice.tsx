import { CRISIS_NOTICE } from '../../services/crisisSafety'
import './crisis-notice.css'

// 캐릭터 대사가 아닌 서비스 시스템 말풍선. 대화를 막는 팝업으로 띄우지 않는다.
export function CrisisNotice() {
  return <aside className="crisis-notice" role="note" aria-label={CRISIS_NOTICE.title}>
    <strong>{CRISIS_NOTICE.title}</strong>
    {CRISIS_NOTICE.lines.map(line => <p key={line}>{line}</p>)}
    <ul>
      {CRISIS_NOTICE.contacts.map(contact => <li key={contact.number}>
        <a href={contact.tel}><span>{contact.label}</span><b>☎ {contact.number}</b></a>
        <small>{contact.note}</small>
      </li>)}
    </ul>
  </aside>
}
