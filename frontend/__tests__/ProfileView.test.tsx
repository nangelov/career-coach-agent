import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { type Session } from "@/lib/auth";
import ProfileView from "@/components/ProfileView";
import {
  getProfile,
  ProfileApiError,
  updateProfile,
  type Profile,
} from "@/lib/profile";

jest.mock("@/lib/profile", () => {
  const actual = jest.requireActual("@/lib/profile");
  return {
    __esModule: true,
    ...actual,
    getProfile: jest.fn(),
    updateProfile: jest.fn(),
  };
});

const mockGetProfile = getProfile as jest.MockedFunction<typeof getProfile>;
const mockUpdateProfile = updateProfile as jest.MockedFunction<typeof updateProfile>;

function session(role: Session["role"] = "user"): Session {
  return {
    sessionId: "sid",
    role,
    expiresAt: Date.now() + 3_600_000,
  };
}

function emptyProfile(): Profile {
  return { skills: [], experience: [], education: [], goals: [] };
}

function populatedProfile(): Profile {
  return {
    skills: ["TypeScript", "React"],
    experience: [
      {
        title: "Engineer",
        company: "Acme",
        start_date: "2020",
        end_date: "Present",
        description: "Built things",
      },
    ],
    education: [
      {
        institution: "Uni",
        degree: "BSc",
        field: "CS",
        start_date: "2015",
        end_date: "2019",
      },
    ],
    goals: ["Become a staff engineer"],
  };
}

beforeEach(() => {
  jest.clearAllMocks();
});

describe("ProfileView", () => {
  it("loads and renders the structured profile", async () => {
    mockGetProfile.mockResolvedValue(populatedProfile());

    render(<ProfileView session={session()} />);

    // Skills render into the one-per-line textarea.
    const skills = await screen.findByLabelText(/skills/i);
    expect(skills).toHaveValue("TypeScript\nReact");
    expect(screen.getByLabelText(/experience 1 title/i)).toHaveValue("Engineer");
    expect(screen.getByLabelText(/education 1 institution/i)).toHaveValue("Uni");
    expect(screen.getByLabelText(/career goals/i)).toHaveValue(
      "Become a staff engineer",
    );
  });

  it("prompts to upload a CV when the profile is empty", async () => {
    mockGetProfile.mockResolvedValue(emptyProfile());

    render(<ProfileView session={session()} />);

    expect(await screen.findByTestId("profile-empty")).toHaveTextContent(
      /don't have a profile yet/i,
    );
  });

  it("edits skills and saves the updated profile", async () => {
    mockGetProfile.mockResolvedValue(populatedProfile());
    mockUpdateProfile.mockImplementation(async (profile) => profile);

    render(<ProfileView session={session()} />);

    const skills = await screen.findByLabelText(/skills/i);
    fireEvent.change(skills, { target: { value: "TypeScript\nRust" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /save profile/i }));
    });

    expect(await screen.findByTestId("profile-saved")).toBeInTheDocument();
    const [saved] = mockUpdateProfile.mock.calls[0];
    expect(saved.skills).toEqual(["TypeScript", "Rust"]);
    // Blank lines are dropped, entries trimmed.
    expect(saved.experience[0]).toMatchObject({ title: "Engineer", company: "Acme" });
  });

  it("adds an experience entry and includes it in the saved payload", async () => {
    mockGetProfile.mockResolvedValue(emptyProfile());
    mockUpdateProfile.mockImplementation(async (profile) => profile);

    render(<ProfileView session={session()} />);
    await screen.findByTestId("profile-view");

    fireEvent.click(screen.getByRole("button", { name: /add experience/i }));
    fireEvent.change(screen.getByLabelText(/experience 1 title/i), {
      target: { value: "Intern" },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /save profile/i }));
    });

    await waitFor(() => expect(mockUpdateProfile).toHaveBeenCalledTimes(1));
    const [saved] = mockUpdateProfile.mock.calls[0];
    expect(saved.experience).toHaveLength(1);
    expect(saved.experience[0].title).toBe("Intern");
  });

  it("shows a clear message (not a raw error) when a guest tries to save", async () => {
    mockGetProfile.mockResolvedValue(emptyProfile());
    mockUpdateProfile.mockRejectedValue(
      new ProfileApiError(
        403,
        "Guests cannot save a profile. Sign in to store and edit your profile.",
      ),
    );

    render(<ProfileView session={session("guest")} />);
    await screen.findByTestId("profile-view");

    // The guest hint is shown up front.
    expect(screen.getByTestId("guest-note")).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /save profile/i }));
    });

    expect(await screen.findByTestId("profile-save-error")).toHaveTextContent(
      /sign in to store and edit/i,
    );
  });

  it("shows a load error when the profile fetch fails", async () => {
    mockGetProfile.mockRejectedValue(new ProfileApiError(500, "Boom"));

    render(<ProfileView session={session()} />);

    expect(await screen.findByTestId("profile-load-error")).toHaveTextContent(/boom/i);
  });

  it("re-fetches the profile when reloadKey changes", async () => {
    mockGetProfile.mockResolvedValue(emptyProfile());

    const { rerender } = render(<ProfileView session={session()} reloadKey={0} />);
    await screen.findByTestId("profile-view");
    expect(mockGetProfile).toHaveBeenCalledTimes(1);

    mockGetProfile.mockResolvedValue(populatedProfile());
    rerender(<ProfileView session={session()} reloadKey={1} />);

    await waitFor(() => expect(mockGetProfile).toHaveBeenCalledTimes(2));
    expect(await screen.findByLabelText(/skills/i)).toHaveValue("TypeScript\nReact");
  });
});
