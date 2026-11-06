/** What a voice preview says, and in which language: a non-English voice speaks its own language. */
const SAMPLES: Record<string, string> = {
  ar: "مرحباً، هذه عينة من صوتي باللغة العربية. كيف يمكنني مساعدتك اليوم؟",
  tl: "Kumusta! Ito ang halimbawa ng aking boses sa Filipino. Paano kita matutulungan ngayon?",
  es: "Hola, esta es una muestra de mi voz en español. ¿Cómo puedo ayudarte hoy?",
  fr: "Bonjour, voici un exemple de ma voix en français. Comment puis-je vous aider aujourd'hui ?",
  de: "Hallo, das ist eine Probe meiner Stimme auf Deutsch. Wie kann ich Ihnen heute helfen?",
  pt: "Olá, esta é uma amostra da minha voz em português. Como posso ajudar você hoje?",
  it: "Ciao, questo è un esempio della mia voce in italiano. Come posso aiutarti oggi?",
  nl: "Hallo, dit is een voorbeeld van mijn stem in het Nederlands. Hoe kan ik je vandaag helpen?",
  hi: "नमस्ते, यह हिंदी में मेरी आवाज़ का एक नमूना है। आज मैं आपकी कैसे मदद कर सकती हूँ?",
  ja: "こんにちは、これは日本語での私の声のサンプルです。今日はどのようにお手伝いできますか？",
  zh: "你好，这是我的中文声音示例。今天我能帮您什么？",
  ko: "안녕하세요, 이것은 한국어로 된 제 목소리 샘플입니다. 오늘 무엇을 도와드릴까요?",
  tr: "Merhaba, bu Türkçe sesimden bir örnek. Bugün size nasıl yardımcı olabilirim?",
  ru: "Здравствуйте, это пример моего голоса на русском языке. Чем я могу вам помочь сегодня?",
  pl: "Dzień dobry, to próbka mojego głosu po polsku. W czym mogę dziś pomóc?",
  vi: "Xin chào, đây là mẫu giọng nói tiếng Việt của tôi. Hôm nay tôi có thể giúp gì cho bạn?",
};

export function voicePreview(voiceLanguage: string | null | undefined, agentLanguage: string, defaultText: string) {
  const own = (voiceLanguage ?? "").toLowerCase().split(/[-_]/)[0];
  const language = own && own !== "en" && SAMPLES[own] ? own : agentLanguage;
  return { language, text: SAMPLES[language] ?? defaultText };
}
