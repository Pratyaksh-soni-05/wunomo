export const CAL_LINK = "https://cal.com/wunomo/demo";

export const FORMSPREE_FORM_ID = "mlgqqyon";
export const FORMSPREE_ENDPOINT = `https://formspree.io/f/${FORMSPREE_FORM_ID}`;

const WHATSAPP_PREFILL = "Hi, I'm interested in Wunomo";

function whatsappLink(digits: string): string {
  return `https://wa.me/${digits}?text=${encodeURIComponent(WHATSAPP_PREFILL)}`;
}

export interface Contact {
  name: string;
  email: string;
  whatsappDigits: string;
  whatsappLink: string;
}

export const CONTACTS: Contact[] = [
  {
    name: "Pratyaksh Soni",
    email: "pratyakshsoni2005@gmail.com",
    whatsappDigits: "917737672577",
    whatsappLink: whatsappLink("917737672577"),
  },
  {
    name: "Daksh Gupta",
    email: "guptadaksh1509@gmail.com",
    whatsappDigits: "919461665538",
    whatsappLink: whatsappLink("919461665538"),
  },
];

// Kept for anything that just wants "an email to fall back to" (e.g. the
// interest form's error state) without caring which person.
export const PRIMARY_CONTACT_EMAIL = CONTACTS[0].email;
