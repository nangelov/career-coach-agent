import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { type Session } from "@/lib/auth";
import MemoryPanel from "@/components/MemoryPanel";
import {
  deleteMemory,
  getMemory,
  MemoryApiError,
  updatePreferences,
  type MemoryView,
} from "@/lib/memory";

jest.mock("@/lib/memory", () => {
  const actual = jest.requireActual("@/lib/memory");
  return {
    __esModule: true,
    ...actual,
    getMemory: jest.fn(),
    updatePreferences: jest.fn(),
    deleteMemory: jest.fn(),
  };
});

const mockGetMemory = getMemory as jest.MockedFunction<typeof getMemory>;
const mockUpdatePreferences = updatePreferences as jest.MockedFunction<
  typeof updatePreferences
>;
const mockDeleteMemory = deleteMemory as jest.MockedFunction<typeof deleteMemory>;

function session(role: Session["role"] = "user"): Session {
  return { sessionId: "sid", role, expiresAt: Date.now() + 3_600_000 };
}

function view(): MemoryView {
  return {
    preferences: {
      tone: "encouraging",
      formality: "casual",
      language: "en",
      focus_areas: ["leadership"],
      avoid: ["jargon"],
    },
    memories: [
      {
        id: "mem1",
        text: "Prefers concise answers",
        memory_type: "preference",
        confidence: 0.9,
        created_at: "2026-07-19T00:00:00Z",
      },
      {
        id: "mem2",
        text: "Targeting an AI architect role",
        memory_type: "goal",
        confidence: 0.7,
        created_at: "2026-07-18T00:00:00Z",
      },
    ],
  };
}

beforeEach(() => {
  jest.clearAllMocks();
});

describe("MemoryPanel", () => {
  it("renders preferences and the learned memories list", async () => {
    mockGetMemory.mockResolvedValue(view());

    render(<MemoryPanel session={session()} />);

    expect(await screen.findByLabelText(/tone/i)).toHaveValue("encouraging");
    expect(screen.getByLabelText(/focus areas/i)).toHaveValue("leadership");
    const items = screen.getAllByTestId("memory-item");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent(/Prefers concise answers/);
    expect(items[0]).toHaveTextContent(/preference/);
    expect(items[0]).toHaveTextContent(/90%/);
  });

  it("saves edited preferences", async () => {
    mockGetMemory.mockResolvedValue(view());
    mockUpdatePreferences.mockImplementation(async (prefs) => prefs);

    render(<MemoryPanel session={session()} />);

    const tone = await screen.findByLabelText(/tone/i);
    fireEvent.change(tone, { target: { value: "direct" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /save preferences/i }));
    });

    expect(await screen.findByTestId("memory-saved")).toBeInTheDocument();
    const [saved] = mockUpdatePreferences.mock.calls[0];
    expect(saved.tone).toBe("direct");
    expect(saved.focus_areas).toEqual(["leadership"]);
  });

  it("deletes a learned memory immediately (no confirmation)", async () => {
    mockGetMemory.mockResolvedValue(view());
    mockDeleteMemory.mockResolvedValue(undefined);

    render(<MemoryPanel session={session()} />);
    await screen.findByTestId("memory-panel");

    expect(screen.getAllByTestId("memory-item")).toHaveLength(2);
    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: /delete memory: prefers concise answers/i }),
      );
    });

    await waitFor(() => expect(mockDeleteMemory).toHaveBeenCalledWith("mem1"));
    expect(screen.getAllByTestId("memory-item")).toHaveLength(1);
  });

  it("restores the memory and shows an error when delete fails", async () => {
    mockGetMemory.mockResolvedValue(view());
    mockDeleteMemory.mockRejectedValue(new MemoryApiError(404, "Memory not found."));

    render(<MemoryPanel session={session()} />);
    await screen.findByTestId("memory-panel");

    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: /delete memory: prefers concise answers/i }),
      );
    });

    expect(await screen.findByTestId("memory-delete-error")).toHaveTextContent(
      /not found/i,
    );
    // The optimistic removal is rolled back.
    expect(screen.getAllByTestId("memory-item")).toHaveLength(2);
  });

  it("shows the empty state when nothing has been learned", async () => {
    mockGetMemory.mockResolvedValue({ ...view(), memories: [] });

    render(<MemoryPanel session={session()} />);

    expect(await screen.findByTestId("memory-empty")).toBeInTheDocument();
  });

  it("shows a guest sign-in state without calling the API", async () => {
    render(<MemoryPanel session={session("guest")} />);

    expect(screen.getByTestId("memory-guest")).toHaveTextContent(
      /sign in to see what the coach has learned/i,
    );
    expect(mockGetMemory).not.toHaveBeenCalled();
  });

  it("shows a load error (not a raw failure) when the fetch fails", async () => {
    mockGetMemory.mockRejectedValue(new MemoryApiError(500, "Boom"));

    render(<MemoryPanel session={session()} />);

    expect(await screen.findByTestId("memory-load-error")).toHaveTextContent(/boom/i);
  });
});
