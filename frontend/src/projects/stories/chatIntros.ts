import room from '../../assets/fridge/fridge-smug.webp'

export type ChatIntroConfig = { messageEntrance?: boolean; background?: string; alt?: string; scene: string }
// 배경 공간 설정은 채팅의 scene_image 메시지 목록과 독립적이다.
export const chatIntros: Record<string, ChatIntroConfig> = {
 fridge: { messageEntrance: true, background: room, alt: '말하는 냉장고가 놓인 작은 원룸', scene: '설치 첫날 밤. 조용한 원룸에서 누군가 말을 걸어온다.' },
 puruma: { scene: '개강 첫날. 길을 잃은 신입생이 선배를 기다리고 있다.' },
 cloud: { scene: '바람섬에서 구조 신호가 도착했다. 구조대와 첫 임무를 시작한다.' },
}
