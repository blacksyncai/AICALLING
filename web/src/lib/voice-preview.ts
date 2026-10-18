/** Arabic clones preview in Arabic even before the agent language is changed. */
export function voicePreview(voiceLanguage: string | null | undefined, agentLanguage: string, defaultText: string) {
  const language = voiceLanguage === "ar" ? "ar" : agentLanguage;
  return { language, text: language === "ar" ? "مرحباً، هذه عينة من صوتي باللغة العربية. كيف يمكنني مساعدتك اليوم؟" : language === "tl" ? "Kumusta! Ito ang halimbawa ng aking boses sa Filipino. Paano kita matutulungan ngayon?" : defaultText };
}
