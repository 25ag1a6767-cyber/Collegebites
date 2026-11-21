import React, { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { LifeBuoy, MessageSquare, Send } from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import { Badge, Button, Card, Input, Select, useToast } from "../../components/ui/Primitives";

export const SupportPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const { user } = useAppStore();
  const { pushToast } = useToast();

  const [category, setCategory] = useState("food_quality");
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");
  const [guestName, setGuestName] = useState("");
  const [guestPhone, setGuestPhone] = useState("");
  const [selectedTicketId, setSelectedTicketId] = useState<string | null>(null);
  const [replyText, setReplyText] = useState("");

  const { data: tickets = [], refetch } = useQuery<any[]>({
    queryKey: ["my-tickets"],
    enabled: Boolean(user),
    queryFn: async () => (await api.get("/support/tickets/my")).data,
  });

  const { data: messages = [], refetch: refetchMessages } = useQuery<any[]>({
    queryKey: ["ticket-messages", selectedTicketId],
    enabled: Boolean(selectedTicketId && user),
    queryFn: async () => (await api.get(`/support/tickets/${selectedTicketId}/messages`)).data,
  });

  const submitTicket = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.post("/support/tickets", {
        order_id: searchParams.get("order_id") || null,
        category,
        subject,
        description,
        guest_name: !user ? guestName : null,
        guest_phone: !user ? guestPhone : null,
      });
      setSubject("");
      setDescription("");
      pushToast("Support ticket submitted! Our canteen team will respond shortly.", "success");
      refetch();
    } catch (err) {
      pushToast(getApiError(err, "Failed to submit ticket"), "error");
    }
  };

  const sendReply = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedTicketId || !replyText.trim()) return;
    try {
      await api.post(`/support/tickets/${selectedTicketId}/messages`, { message: replyText });
      setReplyText("");
      refetchMessages();
    } catch (err) {
      pushToast(getApiError(err), "error");
    }
  };

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 space-y-6">
      <div className="flex items-center gap-3">
        <LifeBuoy className="h-7 w-7 text-orange-600" />
        <div>
          <h1 className="text-2xl font-extrabold text-slate-900">Customer Support & Feedback</h1>
          <p className="text-xs text-slate-500">
            Report food quality, missing items, or order discrepancies. Note: CollegeBites does not process in-app refunds.
          </p>
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Card className="p-5">
          <h2 className="font-bold text-slate-900 mb-4">Submit a Support Ticket</h2>
          <form onSubmit={submitTicket} className="space-y-3">
            {!user && (
              <div className="grid grid-cols-2 gap-3">
                <Input required value={guestName} onChange={(e) => setGuestName(e.target.value)} placeholder="Your Name" />
                <Input required value={guestPhone} onChange={(e) => setGuestPhone(e.target.value)} placeholder="Mobile Number" />
              </div>
            )}
            <div>
              <label className="mb-1 block text-xs font-bold text-slate-700">Issue Category</label>
              <Select value={category} onChange={(e) => setCategory(e.target.value)}>
                <option value="food_quality">Food Quality Issue</option>
                <option value="missing_item">Missing Item</option>
                <option value="incorrect_order">Incorrect Order</option>
                <option value="app_help">App / QR Help</option>
                <option value="other">Other</option>
              </Select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-bold text-slate-700">Subject</label>
              <Input required value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Brief summary..." />
            </div>
            <div>
              <label className="mb-1 block text-xs font-bold text-slate-700">Description</label>
              <textarea
                required
                rows={4}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className="w-full rounded-xl border border-slate-300 p-3 text-sm focus:border-orange-500 focus:outline-none"
                placeholder="Describe what happened with your order..."
              />
            </div>
            <Button type="submit" className="w-full">
              Submit Support Ticket
            </Button>
          </form>
        </Card>

        <Card className="p-5 space-y-4">
          <h2 className="font-bold text-slate-900">Your Tickets ({tickets.length})</h2>
          {!user ? (
            <div className="text-xs text-slate-500">Sign in to view ticket conversation history.</div>
          ) : tickets.length === 0 ? (
            <div className="text-xs text-slate-500">No support tickets filed.</div>
          ) : (
            <div className="space-y-2 max-h-60 overflow-y-auto">
              {tickets.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setSelectedTicketId(t.id)}
                  className={`w-full rounded-xl border p-3 text-left text-xs ${
                    selectedTicketId === t.id ? "border-orange-500 bg-orange-50" : "border-slate-200"
                  }`}
                >
                  <div className="flex items-center justify-between font-bold">
                    <span>
                      {t.ticket_number} • {t.subject}
                    </span>
                    <Badge tone={t.status === "resolved" ? "green" : "amber"}>{t.status}</Badge>
                  </div>
                  <div className="text-slate-500 mt-1">{t.category.replace("_", " ")}</div>
                </button>
              ))}
            </div>
          )}

          {selectedTicketId && (
            <div className="border-t border-slate-200 pt-3 space-y-2">
              <div className="flex items-center gap-1.5 text-xs font-bold text-slate-700">
                <MessageSquare className="h-3.5 w-3.5" /> Conversation
              </div>
              <div className="space-y-1.5 max-h-40 overflow-y-auto">
                {messages.map((m) => (
                  <div key={m.id} className="rounded-lg bg-slate-100 px-3 py-2 text-xs">
                    <span className="font-bold uppercase text-[10px] text-slate-500">{m.sender_role}: </span>
                    {m.message}
                  </div>
                ))}
              </div>
              <form onSubmit={sendReply} className="flex gap-2">
                <Input value={replyText} onChange={(e) => setReplyText(e.target.value)} placeholder="Type a reply..." />
                <Button size="sm" type="submit">
                  <Send className="h-3.5 w-3.5" />
                </Button>
              </form>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
};
