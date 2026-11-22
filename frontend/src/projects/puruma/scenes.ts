import type { Emotion } from '../../features/chat/types'

// 푸르마 10턴 장면 (서버 backend/app/services/puruma_scenes.py와 같은 문장, 백엔드 테스트로 일치 검사).
// 배치: 개강 1-2 / 적응 3-4 / 중간고사 5-6 / 축제 7-8 / 기말·종강 9 / 방학 계획 10 (기획서 6구간·12턴을 10턴으로 줄인 안).
// 고정 SOS·구간 1·3·5·7·9·10턴 선택지·반응 예시·전환 문구는 기획서 3장 원문이다.
// 각 구간 둘째 턴(2·4·6·8턴)의 장면·선택지, 10턴 반응, 자유 입력 대사는 구현 초안이다(기획 검토 전).
// 브라우저 Mock은 이 문장만 보여 주며 스탯·홍보·엔딩 판정을 하지 않는다(서버 Mock·API 모드에서만 판정).

export type SceneChoice = { id: string; label: string; reply: string; emotion: Emotion }
export type PurumaScene = {
  section: number
  sectionTitle: string
  situation: string
  opening: string[]
  openingEmotion: Emotion
  choices: SceneChoice[]
  freeReply: string
  freeEmotion: Emotion
}

export const SCENES: PurumaScene[] = [
  {
    section: 1, sectionTitle: '개강', situation: '첫 수업, 길을 잃었어요!', openingEmotion: 'confused',
    opening: ['선배, 강의실이 어딘지 모르겠어요. 캠퍼스가 너무 넓어서 어디가 어딘지 모르겠어요.'],
    choices: [
      { id: 'c1_t1_a', label: '지도 같이 보자', reply: '지도에 이렇게 나오는 거였구나! 이제 알겠어요.', emotion: 'sparkle' },
      { id: 'c1_t1_b', label: '사람들한테 물어보자', reply: '물어봐도 돼요? 저 낯을 가리는데... 선배가 먼저 말해 주세요.', emotion: 'confused' },
      { id: 'c1_t1_c', label: '내가 데려다줄게', reply: '선배 믿고 따라갈게요! 앞장서 주세요.', emotion: 'happy' },
    ],
    freeReply: '선배, 이야기해 줘서 고마워요! 우선 강의실부터 같이 찾아가 봐요.', freeEmotion: 'happy',
  },
  {
    section: 1, sectionTitle: '개강', situation: '첫 수업, 이미 시작했어요!', openingEmotion: 'confused',
    opening: ['강의실에 도착했는데 벌써 수업 중이에요... 뒷문으로 살금살금 들어가 볼까요?'],
    choices: [
      { id: 'c1_t2_a', label: '천천히, 조용히 들어가자', reply: '살금살금... 앗, 또각! 말발굽 소리가 나 버렸어요. 그래도 선배 덕분에 자리에 앉았어요, 히히힝!', emotion: 'sparkle' },
      { id: 'c1_t2_b', label: '괜찮아, 내가 옆에 있잖아', reply: '선배가 옆에 있으니까 용기가 나요! 또각... 조금 시끄러웠지만 첫 수업에 무사히 들어왔어요, 히히힝!', emotion: 'happy' },
      { id: 'c1_t2_c', label: '인사하고 들어가자', reply: '늦어서 죄송합니다...! 인사하고 들어오니까 마음이 놓여요. 선배, 첫 수업부터 정말 정신없네요!', emotion: 'happy' },
    ],
    freeReply: '선배 말을 들으니 조금 안심돼요. 살금살금... 또각! 그래도 무사히 자리에 앉았어요.', freeEmotion: 'sparkle',
  },
  {
    section: 2, sectionTitle: '적응', situation: '점심시간, 학교가 아직 낯설어요', openingEmotion: 'happy',
    opening: ['여기가 강의실이었어요! 이제 점심이 궁금해요.', '선배, 저 이 학교를 아직 잘 몰라요. 선배가 아는 것 중에 좋은 거, 재미있는 거 아무거나 추천해 주세요!'],
    choices: [
      { id: 'c2_t3_a', label: '맛있는 밥', reply: '선배가 추천하면 믿고 먹을게요! 저 풀만 먹는 거 아니에요, 히히힝.', emotion: 'happy' },
      { id: 'c2_t3_b', label: '같이할 사람, 동아리', reply: '사람이 막 모여 있는 곳이요? 선배랑 같이 가면 안 무서워요.', emotion: 'happy' },
      { id: 'c2_t3_c', label: '공부하기 좋은 곳', reply: '공부요...? 일단 메모해 둘게요. 시험 전에 꺼내 볼게요.', emotion: 'confused' },
      { id: 'c2_t3_d', label: '구경하기 좋은 것', reply: '와, 그런 것도 있어요? 저 구경은 자신 있어요!', emotion: 'sparkle' },
    ],
    freeReply: '오, 그런 것도 있군요! 선배 추천이라 더 궁금해져요.', freeEmotion: 'sparkle',
  },
  {
    section: 2, sectionTitle: '적응', situation: '한 학기 위시리스트', openingEmotion: 'sparkle',
    opening: ['선배 추천, 한 학기 위시리스트에 넣었어요! 또 뭐 없어요? 하나만 더 알려 주세요!'],
    choices: [
      { id: 'c2_t4_a', label: '점심은 학식 어때?', reply: '학식이요? 말도 먹을 수 있는 메뉴가 있으면 좋겠어요!', emotion: 'happy' },
      { id: 'c2_t4_b', label: '동아리 구경도 해 봐', reply: '동아리 구경이요? 선배가 같이 가 주면 용기 낼게요!', emotion: 'happy' },
      { id: 'c2_t4_c', label: '천천히 둘러봐도 돼', reply: '맞아요, 서두르지 않을게요. 선배 말 들으니까 마음이 편해요.', emotion: 'happy' },
    ],
    freeReply: '그것도 위시리스트에 넣을게요! 히히힝, 벌써 한 줄이 꽉 찼어요.', freeEmotion: 'sparkle',
  },
  {
    section: 3, sectionTitle: '중간고사', situation: '시험 2주 전, 도서관 앞', openingEmotion: 'confused',
    opening: ['벌써 시험이래요... 시간이 너무 빨라요.', '선배, 중간고사가 코앞인데 아직 아무것도 못 했어요... 어디서 공부하면 좋을까요? 중앙도서관이 좋다던데, 자리가 있을까요?'],
    choices: [
      { id: 'c3_t5_a', label: '도서관 가서 같이 공부하자', reply: '같이 가 주시면 힘이 나요! 오늘은 끝까지 해 볼게요.', emotion: 'sparkle' },
      { id: 'c3_t5_b', label: '스터디를 만들어 보자', reply: '스터디요? 친구를 사귈 수 있겠어요!', emotion: 'happy' },
      { id: 'c3_t5_c', label: '쉬면서 해', reply: '맞아요, 무리하면 머리가 터질 것 같아요.', emotion: 'happy' },
    ],
    freeReply: '선배 말 듣고 나니 조금 덜 막막해요. 일단 오늘 할 것부터 정해 볼게요.', freeEmotion: 'happy',
  },
  {
    section: 3, sectionTitle: '중간고사', situation: '공부하다 쉬는 시간', openingEmotion: 'confused',
    opening: ['선배, 공부하다가 잠깐 쉬는 중이에요. 책을 펴 놓으면 자꾸 눈이 감겨요... 어떻게 하면 집중이 잘 돼요?'],
    choices: [
      { id: 'c3_t6_a', label: '같이 계획 세워 보자', reply: '계획표요? 선배랑 짜면 저도 지킬 수 있을 것 같아요!', emotion: 'sparkle' },
      { id: 'c3_t6_b', label: '잠깐 산책하고 오자', reply: '산책 좋아요! 다리를 좀 풀면 머리도 맑아질 것 같아요, 히히힝.', emotion: 'happy' },
      { id: 'c3_t6_c', label: '오늘은 일찍 자', reply: '일찍 자는 것도 공부래요? 선배 말이면 믿어 볼게요.', emotion: 'happy' },
    ],
    freeReply: '선배 방법대로 해 볼게요. 조금씩이라도 하면 되겠죠?', freeEmotion: 'happy',
  },
  {
    section: 4, sectionTitle: '축제', situation: '축제 기간, 들뜬 캠퍼스', openingEmotion: 'sparkle',
    opening: ['시험 끝났다! 이제 축제만 남았어요!', '선배! 축제래요! 어디서 노래도 나고 맛있는 냄새도 나요! 저 선배랑 같이 가고 싶어요!'],
    choices: [
      { id: 'c4_t7_a', label: '공연부터 보자', reply: '노래가 막 울려요! 저도 몸이 들썩들썩해요, 히히힝!', emotion: 'sparkle' },
      { id: 'c4_t7_b', label: '푸드트럭부터 가자', reply: '줄이 엄청 길어요! 근데 냄새가 너무 좋아서 기다릴 수 있어요.', emotion: 'happy' },
      { id: 'c4_t7_c', label: '너 혼자 다녀와', reply: '저 혼자요...? 용기를 내 볼게요. 다녀올게요!', emotion: 'confused' },
    ],
    freeReply: '선배랑 축제라니 벌써 신나요! 어디부터 갈지 같이 골라요.', freeEmotion: 'sparkle',
  },
  {
    section: 4, sectionTitle: '축제', situation: '푸드트럭과 공연', openingEmotion: 'confused',
    opening: ['선배, 저기 무대에서 곧 공연이 시작한대요! 그 전에 뭐 좀 먹을까요? 근데... 말이 먹어도 되는 걸까요?'],
    choices: [
      { id: 'c4_t8_a', label: '이거 먹어 봐', reply: '선배가 골라 주는 거면 믿고 먹을게요! 음, 맛있어요!', emotion: 'happy' },
      { id: 'c4_t8_b', label: '같이 공연 보면서 먹자', reply: '좋아요! 노래 들으면서 먹으니까 더 맛있어요. 이 시간이 오래갔으면 좋겠어요.', emotion: 'sparkle' },
      { id: 'c4_t8_c', label: '천천히 골라도 돼', reply: '히히힝, 고민하는 것도 축제의 재미 같아요. 선배는 뭐 먹을 거예요?', emotion: 'happy' },
    ],
    freeReply: '선배 덕분에 축제가 더 즐거워요. 이 시간이 오래갔으면 좋겠어요.', freeEmotion: 'sparkle',
  },
  {
    section: 5, sectionTitle: '기말·종강', situation: '종강 직전, 성적 걱정', openingEmotion: 'confused',
    opening: ['축제 정말 즐거웠어요. 근데 이제 성적이...', '선배... 성적이 무서워요. 장학금은 받을 수 있을까요?'],
    choices: [
      { id: 'c5_t9_a', label: '막판 스퍼트하자', reply: '알겠어요, 끝까지 달려 볼게요!', emotion: 'sparkle' },
      { id: 'c5_t9_b', label: '계획을 세워 보자', reply: '계획표요? 선배가 짜 주는 거면 믿고 따를게요.', emotion: 'happy' },
      { id: 'c5_t9_c', label: '응원만 할게', reply: '응원만으로도 힘이 나요, 고마워요 선배.', emotion: 'happy' },
    ],
    freeReply: '선배 말 들으니까 조금 덜 무서워요. 끝까지 해 볼게요.', freeEmotion: 'happy',
  },
  {
    section: 6, sectionTitle: '방학 계획', situation: '종강 후, 앞으로의 길', openingEmotion: 'confused',
    opening: ['한 학기가 끝났어요. 선배 덕분이에요.', '선배, 이제 방학이에요. 저... 이제 뭘 해야 하는지 모르겠어요. 진로도 정해야 할 것 같고요. 선배는 어떻게 생각해요?'],
    choices: [
      { id: 'c6_t10_a', label: '취업 준비를 해 보자', reply: '취업 준비요? 저도 그쪽이 궁금했어요. 같이 알아봐요.', emotion: 'sparkle' },
      { id: 'c6_t10_b', label: '교환학생을 알아보자', reply: '교환학생이요? 저도 그쪽이 궁금했어요. 같이 알아봐요.', emotion: 'sparkle' },
      { id: 'c6_t10_c', label: '비교과 활동을 해 보자', reply: '비교과 활동이요? 저도 그쪽이 궁금했어요. 같이 알아봐요.', emotion: 'sparkle' },
      { id: 'c6_t10_d', label: '창업을 해 보자', reply: '창업이요? 저도 그쪽이 궁금했어요. 같이 알아봐요.', emotion: 'sparkle' },
    ],
    freeReply: '선배 이야기 들으니까 방학이 기대돼요. 저만의 길, 천천히 찾아볼게요.', freeEmotion: 'sparkle',
  },
]

export const TOTAL_TURNS = SCENES.length
export const SECTION_COUNT = 6
export const openingText = (turn: number) => SCENES[turn].opening.join('\n')

// 시연용 엔딩 6종 (기획서 6.1 문구 그대로, 판정은 서버 backend/app/services/puruma_state.py).
export type PurumaEnding = { id: string; title: string; layer: '히든' | '홍보' | '재미'; description: string }
export const PURUMA_ENDINGS: PurumaEnding[] = [
  { id: 'career_prep_pruma', title: '취업 준비 푸르마', layer: '홍보', description: '푸르마는 벌써 다음 학기 계획표를 짰어요. 선배가 건넨 한마디가 방향이 되었어요.' },
  { id: 'library_ghost_pruma', title: '도서관 지박령 푸르마', layer: '홍보', description: '푸르마는 한 학기 내내 도서관 불이 꺼질 때까지 자리를 지켰어요. 선배 덕분에 든든한 한 학기였대요.' },
  { id: 'exchange_pruma', title: '교환학생 푸르마', layer: '재미', description: '푸르마는 하늘을 넘어 바다 건너를 꿈꾸게 됐어요. 짐 싸는 날이 벌써 기대돼요.' },
  { id: 'leave_pruma', title: '휴학 푸르마', layer: '재미', description: '푸르마는 책상에서 한 발짝도 안 움직이다 번아웃이 와 버렸어요. 잠깐 쉬어 가기로 했대요. 다음엔 선배랑 천천히 달려 보고 싶대요.' },
  { id: 'survivor_pruma', title: '종강 생존 푸르마', layer: '재미', description: '푸르마는 무사히 한 학기를 버텼어요! 완벽하진 않았지만 선배와 함께라서 괜찮았어요.' },
  { id: 'cc_pruma', title: 'CC 푸르마', layer: '히든', description: '푸르마가 축제에서 누군가를 만났대요. 선배는 조용히 응원하기로 했어요.' },
]
