/* Hindi for the app's own words (menus, headings, buttons, labels). Names and figures from Tally are never
   touched: only text that matches one of these phrases exactly is shown in Hindi. Chosen per phone in Settings. */
const HI = {
  // bottom bar and side menu
  "Home": "होम", "Sales": "बिक्री", "Ledgers": "लेजर", "Vouchers": "वाउचर", "Dues": "बकाया", "Reports": "रिपोर्ट", "Settings": "सेटिंग्स",
  // home
  "You will receive": "आपको मिलना है", "You owe": "आपको देना है", "See dues": "बकाया देखें", "See dues →": "बकाया देखें →",
  "Sales by day": "रोज़ की बिक्री", "Bank balances": "बैंक बैलेंस", "Latest entries": "हाल की एंट्री", "All dues": "सारे बकाया",
  "Biggest dues": "सबसे बड़े बकाया", "this financial year": "इस वित्त वर्ष", "this month": "इस महीने", "purchases this year": "इस साल की खरीद",
  "New entry": "नई एंट्री", "Entries": "एंट्री", "Sales target": "बिक्री लक्ष्य", "Change": "बदलें", "Set a monthly sales target": "मासिक बिक्री लक्ष्य रखें",
  "Send month-end statements": "महीने के अंत के स्टेटमेंट भेजें", "Nobody owes you money right now.": "अभी किसी पर आपका पैसा बकाया नहीं है।",
  "No vouchers synced yet.": "अभी तक कोई वाउचर सिंक नहीं हुआ।",
  // reports list
  "Entries from phone": "फ़ोन से एंट्री", "Receipts, payments and orders made in the app, and their status": "ऐप में बनी रसीद, भुगतान और ऑर्डर, और उनकी स्थिति",
  "Search and open any voucher": "कोई भी वाउचर खोजें और खोलें", "Day Book": "डे बुक", "Every voucher by date": "तारीख के हिसाब से हर वाउचर",
  "Sales analysis": "बिक्री विश्लेषण", "Top customers and items, margins, this year against last, slow stock": "बड़े ग्राहक और आइटम, मार्जिन, पिछले साल से तुलना, धीमा स्टॉक",
  "Profit & Loss": "लाभ-हानि", "Sales, purchases, expenses and profit": "बिक्री, खरीद, खर्च और मुनाफ़ा",
  "Balance Sheet": "बैलेंस शीट", "What the business owns and owes, as on today": "आज की तारीख में व्यापार की संपत्ति और देनदारी",
  "Cash and bank book": "कैश और बैंक बुक", "Cash and bank": "कैश और बैंक", "Money in and out each day, with opening and closing balances": "हर दिन आया-गया पैसा, शुरुआती और अंतिम बैलेंस के साथ",
  "Bank reconciliation": "बैंक मिलान", "Match your bank statement with the bank ledger in Tally": "बैंक स्टेटमेंट को Tally के बैंक लेजर से मिलाएँ",
  "Follow-up list": "फ़ॉलो-अप सूची", "Who should pay you: overdue, due this week, promises": "किसे भुगतान करना है: बकाया, इस हफ़्ते देय, वादे",
  "Compare periods": "अवधि की तुलना", "This month, quarter or year against the last one and a year ago": "यह महीना, तिमाही या साल, पिछले और एक साल पहले से तुलना",
  "Item profit": "आइटम पर मुनाफ़ा", "Profit on each item and each customer, at Tally's purchase cost": "Tally की खरीद लागत पर हर आइटम और हर ग्राहक पर मुनाफ़ा",
  "Reorder list": "दोबारा मँगाने की सूची", "Items to buy now, by supplier, ready to send": "अभी खरीदने वाले आइटम, सप्लायर के हिसाब से, भेजने को तैयार",
  "Cash flow forecast": "नकदी का अनुमान", "Cash and bank over the next 30 days, from bills falling due and usual expenses": "देय बिलों और सामान्य खर्च से, अगले 30 दिन का कैश और बैंक",
  "Customers who stopped buying": "ग्राहक जिन्होंने खरीदना बंद किया", "Regular buyers who haven't bought for a while, to call back": "नियमित ग्राहक जिन्होंने कुछ समय से नहीं खरीदा, उन्हें फ़ोन करें",
  "Month-end statements": "महीने के अंत के स्टेटमेंट", "Send every customer their statement on WhatsApp, one tap each": "हर ग्राहक को WhatsApp पर उसका स्टेटमेंट भेजें, एक टैप में",
  "Price list": "रेट लिस्ट", "Your items and rates as a PDF to share": "आपके आइटम और रेट, भेजने के लिए PDF में",
  "GSTR-2B matching": "GSTR-2B मिलान", "Upload the GSTR-2B from the GST portal and match it with your purchase bills": "GST पोर्टल से GSTR-2B अपलोड करें और खरीद बिलों से मिलाएँ",
  "E-invoice and e-way bills": "ई-इनवॉइस और ई-वे बिल", "Sales that seem to need an e-invoice or e-way bill but have none": "बिक्री जिन पर ई-इनवॉइस या ई-वे बिल चाहिए पर नहीं है",
  "TDS and TCS": "TDS और TCS", "Deducted each month by section and party, paid, and due dates": "हर महीने कटौती, सेक्शन और पार्टी के हिसाब से, जमा और देय तारीख",
  "Cheque register": "चेक रजिस्टर", "Post-dated and uncleared cheques, received and issued, with reminders": "पोस्ट-डेटेड और बिना क्लियर चेक, मिले और दिए, याद दिलाने के साथ",
  "Stock count": "स्टॉक गिनती", "Count stock on the phone and compare with Tally": "फ़ोन पर स्टॉक गिनें और Tally से मिलाएँ",
  "Year-end checklist": "साल के अंत की जाँच सूची", "What to tidy in Tally before closing the year": "साल बंद करने से पहले Tally में क्या ठीक करें",
  "Staff activity": "स्टाफ़ की गतिविधि", "Who made which entry, reminder or change in the app, and when": "किसने कब कौन सी एंट्री, रिमाइंडर या बदलाव किया",
  "Quotations": "कोटेशन", "Make and share quotations; turn one into a sales order": "कोटेशन बनाएँ और भेजें; उसे सेल्स ऑर्डर में बदलें",
  "Group summary": "ग्रुप सारांश", "Balances by Tally group": "Tally ग्रुप के हिसाब से बैलेंस",
  "Outstanding": "बकाया सूची", "Bill-wise dues with ageing": "बिल के हिसाब से बकाया, पुरानेपन के साथ",
  "Stock summary": "स्टॉक सारांश", "Quantity and value of every item": "हर आइटम की मात्रा और मूल्य", "Stock": "स्टॉक",
  "Who owes what, with bills": "किस पर कितना बकाया, बिलों के साथ", "Overdue and due this week": "बकाया और इस हफ़्ते देय", "Items in hand": "हाथ में आइटम",
  "Daily sales": "रोज़ की बिक्री", "Search any voucher": "कोई भी वाउचर खोजें", "Due dates": "देय तारीखें", "Reminders": "रिमाइंडर",
  // common buttons and words
  "Share PDF": "PDF भेजें", "Print": "प्रिंट", "View PDF": "PDF देखें", "Save": "सेव करें", "Cancel": "रद्द करें", "Approve": "मंज़ूर करें",
  "Reject": "अस्वीकार करें", "Send": "भेजें", "Again": "फिर से", "Copy list": "सूची कॉपी करें", "Copy differences": "अंतर कॉपी करें", "Share": "भेजें",
  "Delete": "हटाएँ", "Open": "खोलें", "Party ledger": "पार्टी लेजर", "Say thank you": "धन्यवाद भेजें", "Try again": "फिर से कोशिश करें",
  "Update app": "ऐप अपडेट करें", "Change server address": "सर्वर का पता बदलें", "Log out": "लॉग आउट", "Logout": "लॉग आउट",
  "Statement": "स्टेटमेंट", "Pending bills": "बाकी बिल", "Items": "आइटम", "Accounts": "खाते", "Bill references": "बिल संदर्भ",
  "Received": "मिले", "Issued": "दिए", "All": "सभी", "Not counted": "गिने नहीं", "Differences": "अंतर", "By item": "आइटम के हिसाब से",
  "By customer": "ग्राहक के हिसाब से", "Start counting": "गिनती शुरू करें", "Finish count": "गिनती पूरी करें", "Open again": "फिर खोलें",
  "Upload and match": "अपलोड करें और मिलाएँ", "Matched": "मिल गए", "Tax differs": "टैक्स अलग है", "In 2B, not in Tally": "2B में है, Tally में नहीं",
  "In Tally, not in 2B": "Tally में है, 2B में नहीं", "Credit at risk": "जोखिम में क्रेडिट", "Matched with Tally": "Tally से मिल गए",
  "Need an e-invoice": "ई-इनवॉइस चाहिए", "Need an e-way bill": "ई-वे बिल चाहिए", "Cash to pay": "नकद भुगतान", "Credit carried forward": "आगे ले जाया क्रेडिट",
  "Cash and bank today": "आज कैश और बैंक", "Lowest point": "सबसे कम स्तर", "Day by day": "दिन-ब-दिन", "Short": "कम", "Extra": "ज़्यादा",
  "Deducted / collected": "काटा / वसूला", "Still to pay now": "अभी जमा करना है", "Month by month": "महीने-दर-महीने",
  "By section (ledger)": "सेक्शन (लेजर) के हिसाब से", "By party": "पार्टी के हिसाब से", "Profit on goods sold": "बेचे माल पर मुनाफ़ा",
  "Sales of stock items": "स्टॉक आइटम की बिक्री", "Person": "व्यक्ति", "Everyone": "सभी", "Rates including GST": "GST सहित रेट",
  "Only items in stock": "केवल स्टॉक में मौजूद आइटम", "All stock groups": "सभी स्टॉक ग्रुप", "Narration (optional)": "विवरण (वैकल्पिक)",
  "Bill photo (optional)": "बिल की फ़ोटो (वैकल्पिक)", "Amount": "राशि", "Date": "तारीख", "Party": "पार्टी", "Note": "नोट",
  // settings
  "Tally and this phone": "Tally और यह फ़ोन", "Syncing from Tally": "Tally से सिंक", "Offline copy": "ऑफ़लाइन कॉपी",
  "Android app, lock and widget": "Android ऐप, लॉक और विजेट", "Customers and money": "ग्राहक और पैसा", "UPI payments": "UPI भुगतान",
  "Customer links": "ग्राहक लिंक", "Interest on overdue bills": "बकाया बिलों पर ब्याज", "Credit warning": "क्रेडिट चेतावनी",
  "Telegram summary and alerts": "Telegram सारांश और अलर्ट", "People and security": "लोग और सुरक्षा", "Staff logins": "स्टाफ़ लॉगिन",
  "App password": "ऐप पासवर्ड", "Your data": "आपका डेटा", "Backups": "बैकअप", "Companies and old data": "कंपनियाँ और पुराना डेटा",
  "Language": "भाषा", "Change your password": "अपना पासवर्ड बदलें", "Change password": "पासवर्ड बदलें", "Current password": "मौजूदा पासवर्ड",
  "New password": "नया पासवर्ड", "New password again": "नया पासवर्ड दोबारा", "App lock": "ऐप लॉक", "Home-screen widget": "होम-स्क्रीन विजेट",
  "Payment notifications": "भुगतान सूचनाएँ", "What's new": "नया क्या है",
};
const HI_ATTR = { "Search items": "आइटम खोजें", "Find an item": "आइटम खोजें", "Search": "खोजें", "Search ledgers": "लेजर खोजें", "Search vouchers": "वाउचर खोजें" };

function hindiOn() { try { return localStorage.getItem("lang") === "hi"; } catch (e) { return false; } }

function translateHi(root) {
  if (!root || !hindiOn()) return;
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => n.parentElement && !n.parentElement.closest("script,style,textarea,input,[data-notr]") ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT });
  const nodes = [];
  while (w.nextNode()) nodes.push(w.currentNode);
  for (const n of nodes) {
    const t = n.nodeValue, k = t.trim();
    if (k && HI[k] !== undefined) n.nodeValue = t.replace(k, HI[k]);
  }
  if (root.querySelectorAll) root.querySelectorAll("[placeholder]").forEach((el) => { const p = el.getAttribute("placeholder"); if (HI_ATTR[p]) el.setAttribute("placeholder", HI_ATTR[p]); });
}

(function () {
  if (!hindiOn()) return;
  document.documentElement.lang = "hi";
  const go = () => {
    translateHi(document.body);
    new MutationObserver((ms) => { for (const m of ms) m.addedNodes.forEach((n) => { if (n.nodeType === 1) translateHi(n); else if (n.nodeType === 3 && n.parentElement) translateHi(n.parentElement); }); })
      .observe(document.body, { childList: true, subtree: true });
  };
  if (document.body) go(); else document.addEventListener("DOMContentLoaded", go);
})();
