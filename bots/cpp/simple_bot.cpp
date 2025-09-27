// C++17 port of simple_bot.py TCP poker bot translated by ChatGPT
// Authored by ChatGPT, run at your own risk.

// Requires: nlohmann/json (https://github.com/nlohmann/json) as a header-only include.
//   Place json.hpp next to this file or in your include path.

// Compile and run:
// g++ -std=gnu++17 -O2 -pthread simple_bot.cpp -o simple_bot
// ./simple_bot --host 0.0.0.0 --port 5001 --name Simple

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <map>
#include <netinet/in.h>
#include <optional>
#include <random>
#include <set>
#include <stdexcept>
#include <string>
#include <sys/socket.h>
#include <unistd.h>
#include <vector>
#include <thread>

#include "json.hpp"
using json = nlohmann::json;

// --- logging toggle
static bool g_verbose = true;
static void vlog(const std::string& s){ if (g_verbose) std::cerr << s << "\n"; }

struct Card {
    char suit; // 'H','D','C','S'
    int  rank; // 2..14 (assumes 'A' => 14)
};

struct Deck {
    std::vector<Card> cards;
    Deck() {
        const std::array<char,4> suits = {'H','D','C','S'};
        for (char s : suits) {
            for (int r = 2; r <= 14; ++r) {
                cards.push_back({s, r});
            }
        }
    }
    void remove(const Card& c) {
        auto it = std::find_if(cards.begin(), cards.end(), [&](const Card& x){
            return x.suit == c.suit && x.rank == c.rank;
        });
        if (it != cards.end()) cards.erase(it);
    }
};

// --- fixed sender
static void send_json(int fd, const json& j) {
    std::string payload = j.dump(-1, ' ', false, json::error_handler_t::replace);

    // Correct big-endian 32-bit length (DON'T manually shift after htonl)
    uint32_t len = static_cast<uint32_t>(payload.size());
    uint32_t be  = htonl(len);

    if (g_verbose) {
        vlog("[send_json] bytes=" + std::to_string(len) + " body=" + payload);
    }

    // write header
    ssize_t w = ::send(fd, &be, 4, MSG_NOSIGNAL);
    if (w != 4) throw std::runtime_error("send header failed");

    // write body
    size_t off = 0;
    while (off < payload.size()) {
        ssize_t k = ::send(fd, payload.data()+off, payload.size()-off, MSG_NOSIGNAL);
        if (k <= 0) throw std::runtime_error("send body failed");
        off += static_cast<size_t>(k);
    }
}


static std::string recvall(int fd, size_t need) {
    std::string buf;
    buf.resize(need);
    size_t off = 0;
    while (off < need) {
        ssize_t k = ::recv(fd, &buf[off], need-off, 0);
        if (k <= 0) throw std::runtime_error("socket closed early");
        off += static_cast<size_t>(k);
    }
    return buf;
}

static json recv_json(int fd, size_t max_bytes = (1u<<20)) {
    auto hdr = recvall(fd, 4);
    uint32_t n = (static_cast<uint8_t>(hdr[0])<<24) |
                 (static_cast<uint8_t>(hdr[1])<<16) |
                 (static_cast<uint8_t>(hdr[2])<<8)  |
                  static_cast<uint8_t>(hdr[3]);
    if (n > max_bytes) throw std::runtime_error("message too large");
    auto body = recvall(fd, n);
    return json::parse(body, /*cb*/nullptr, /*allow_exceptions*/true);
}

// --- Helpers mirroring Python bot logic -------------------------------------

static double flush_odds(const std::vector<Card>& hand,
                         const std::vector<Card>& board,
                         const Deck& deck_left)
{
    std::map<char,int> suit_counts;
    for (auto& c : hand)  suit_counts[c.suit]++;
    for (auto& c : board) suit_counts[c.suit]++;

    std::map<char,int> deck_suits;
    for (auto& c : deck_left.cards) deck_suits[c.suit]++;

    int total_left = (int)deck_left.cards.size();
    if (total_left == 0) return 0.0;

    double max_chance = 0.0;
    for (auto& kv : suit_counts) {
        char s = kv.first;
        int  count = kv.second;
        if (count >= 5) return 1.0;
        int need = 5 - count;
        double p_one = (double)deck_suits[s] / (double)total_left;
        double chance = 1.0;
        for (int i=0;i<need;i++) chance *= p_one; // crude independence approx
        max_chance = std::max(max_chance, chance);
    }
    return max_chance;
}

static double three_odds(const std::vector<Card>& hand,
                         const std::vector<Card>& board,
                         const Deck& deck_left,
                         int draws_left)
{
    std::map<int,int> rank_counts;
    for (auto& c : hand)  rank_counts[c.rank]++;
    for (auto& c : board) rank_counts[c.rank]++;

    std::map<int,int> deck_rank_counts;
    for (auto& c : deck_left.cards) deck_rank_counts[c.rank]++;

    int max_count = 0;
    std::set<int> max_ranks;
    for (auto& kv : rank_counts) {
        int r = kv.first, cnt = kv.second;
        if (cnt >= 3) return 1.0;
        if (cnt > max_count) {
            max_count = cnt;
            max_ranks.clear();
            max_ranks.insert(r);
        } else if (cnt == max_count) {
            max_ranks.insert(r);
        }
    }
    if (max_count == 0) return 0.0;

    int total_left = (int)deck_left.cards.size();
    if (total_left == 0) return 0.0;

    double odd = 0.0;
    int need = 3 - max_count;
    for (int r : max_ranks) {
        double p_one = (double)deck_rank_counts[r] / (double)total_left;
        double p = 1.0;
        for (int i=0;i<need;i++) p *= p_one;
        odd += p;
    }
    // chance across remaining draws (crude):
    return 1.0 - std::pow(1.0 - odd, std::max(1, draws_left));
}

static double quad_odds(const std::vector<Card>& hand,
                        const std::vector<Card>& board,
                        const Deck& deck_left,
                        int draws_left)
{
    std::map<int,int> rank_counts;
    for (auto& c : hand)  rank_counts[c.rank]++;
    for (auto& c : board) rank_counts[c.rank]++;

    std::map<int,int> deck_rank_counts;
    for (auto& c : deck_left.cards) deck_rank_counts[c.rank]++;

    int max_count = 0;
    std::set<int> max_ranks;
    for (auto& kv : rank_counts) {
        int r = kv.first, cnt = kv.second;
        if (cnt >= 4) return 1.0;
        if (cnt > max_count) {
            max_count = cnt;
            max_ranks.clear();
            max_ranks.insert(r);
        } else if (cnt == max_count) {
            max_ranks.insert(r);
        }
    }

    int total_left = (int)deck_left.cards.size();
    if (total_left == 0) return 0.0;

    double odd = 0.0;
    int need = std::max(0, 4 - max_count);
    for (int r : max_ranks) {
        double p_one = (double)deck_rank_counts[r] / (double)total_left;
        double p = 1.0;
        for (int i=0;i<need;i++) p *= p_one;
        odd += p;
    }
    return 1.0 - std::pow(1.0 - odd, std::max(1, draws_left));
}

static bool has_pair_or_better(const std::vector<Card>& hand,
                               const std::vector<Card>& board)
{
    std::map<int,int> cnt;
    for (auto& c : hand)  cnt[c.rank]++;
    for (auto& c : board) cnt[c.rank]++;
    bool pair=false, trips=false, quads=false;
    for (auto& kv : cnt) {
        if (kv.second >= 4) quads = true;
        else if (kv.second == 3) trips = true;
        else if (kv.second == 2) pair = true;
    }
    return quads || trips || pair;
}

static bool made_trips_or_flush(const std::vector<Card>& hand,
                                const std::vector<Card>& board)
{
    std::map<int,int> rc;
    std::map<char,int> sc;
    for (auto& c : hand)  { rc[c.rank]++; sc[c.suit]++; }
    for (auto& c : board) { rc[c.rank]++; sc[c.suit]++; }
    for (auto& kv : rc) if (kv.second >= 3) return true;
    for (auto& kv : sc) if (kv.second >= 5) return true;
    return false;
}

// --- Bot core ---------------------------------------------------------------

struct Bot {
    std::string name = "MyBot";
    std::string host = "127.0.0.1";
    int port = 5001;
    bool running = true;

    static int to_rank(const std::string& r) {
        // Expect either integer or "A","K","Q","J","T"
        if (r.size()==1) {
            char c = r[0];
            if (c>='2' && c<='9') return c-'0';
            if (c=='T') return 10;
            if (c=='J') return 11;
            if (c=='Q') return 12;
            if (c=='K') return 13;
            if (c=='A') return 14;
        }
        // fallback to numeric
        try { return std::stoi(r); } catch (...) { return 0; }
    }

    static Card parse_card(const json& jc) {
        Card c;
        // Python bot used dict { "suit": "...", "rank": "..." }
        std::string s = jc.value("suit", "H");
        std::string r = jc.value("rank", "2");
        c.suit = s.empty()? 'H' : s[0];
        c.rank = to_rank(r);
        return c;
    }

    json decide_action(const json& state) {
        // mirror Python fields
        int player_curr_bet = state.value("player_curr_bet", 0);
        int curr_bet        = state.value("curr_bet", 0);
        int pot             = state.value("pot", 0);
        bool can_check      = state.value("can_check", false);
        int big_blind       = state.value("big_blind", 0);
        int small_blind     = state.value("small_blind", 0);

        // players[name].chips
        int player_stack = 0;
        if (state.contains("players") && state["players"].contains(name)) {
            player_stack = state["players"][name].value("chips", 0);
        }

        std::vector<Card> board, hand;
        if (state.contains("board")) {
            for (auto& jc : state["board"]) board.push_back(parse_card(jc));
        }
        if (state.contains("hand")) {
            for (auto& jc : state["hand"]) hand.push_back(parse_card(jc));
        }

        Deck deck;
        for (auto& c : hand)  deck.remove(c);
        for (auto& c : board) deck.remove(c);
        int draws_left = 5 - (int)board.size();

        double pot_odds = 1.0;
        if (pot > 0) {
            double denom = (double)(pot + curr_bet - player_curr_bet);
            pot_odds = denom > 0 ? (double)curr_bet / denom : 1.0;
        }

        auto f_odds   = flush_odds(hand, board, deck);
        auto t_odds   = three_odds(hand, board, deck, draws_left);
        auto q_odds   = quad_odds(hand, board, deck, draws_left);

        // Approximate the Python "made hand" check (it used evaluate_hand)
        if (draws_left <= 2) {
            if (made_trips_or_flush(hand, board)) {
                // "good hand"
                if (curr_bet < player_stack / 2) {
                    return json{{"move","raise"},{"amount", std::max(1, player_stack/2)}};
                }
                return json{{"move","call"}};
            }
            if (has_pair_or_better(hand, board)) {
                if ((int)(curr_bet * 0.5) < player_stack / 2) {
                    return json{{"move","raise"},{"amount", std::max(1, curr_bet/2)}};
                }
                return json{{"move","call"}};
            }
            if (draws_left == 0) {
                // showdown with nothing: cheap call, else fold
                if (curr_bet - player_curr_bet == 0) return json{{"move","check"}};
                if (curr_bet - player_curr_bet <= std::max(1, player_stack/20))
                    return json{{"move","call"}};
            }
        }

        if (player_stack < big_blind * 2) {
            return json{{"move","call"}};
        }

        if (f_odds <= 0.5 && t_odds <= 0.4 && draws_left <= 1) {
            if (curr_bet - player_curr_bet == 0) return json{{"move","call"}};
            return json{{"move","fold"}};
        }

        if (f_odds >= 0.5 || t_odds >= 0.6 || q_odds >= 0.2) {
            if (player_stack / 10 > curr_bet) {
                return json{{"move","raise"},{"amount", std::max(1, player_stack/10)}};
            }
            if (player_stack > (curr_bet - player_curr_bet)) {
                return json{{"move","call"}};
            }
        }

        if ((curr_bet - player_curr_bet) <= std::max(1, player_stack/10) || draws_left >= 2) {
            return json{{"move","call"}};
        }
        return json{{"move","fold"}};
    }

    void end_game(const json& /*state*/) {
        // no-op (mirror Python)
    }

    int serve() {
        int fd = ::socket(AF_INET, SOCK_STREAM, 0);
        if (fd < 0) { perror("socket"); return 1; }

        int yes = 1;
        setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));

        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_port = htons((uint16_t)port);
        addr.sin_addr.s_addr = INADDR_ANY; // bind all (host flag is for announcement only)
        if (::bind(fd, (sockaddr*)&addr, sizeof(addr)) < 0) {
            perror("bind");
            ::close(fd);
            return 1;
        }
        if (::listen(fd, 16) < 0) {
            perror("listen");
            ::close(fd);
            return 1;
        }
        std::cerr << "[" << name << "] Listening on " << host << ":" << port << " ...\n";

        // main accept loop
        while (running) {
            sockaddr_in cli{};
            socklen_t clilen = sizeof(cli);
            int cfd = ::accept(fd, (sockaddr*)&cli, &clilen);
            if (cfd < 0) {
                // transient errors are fine
                continue;
            }
            try {
                auto req = recv_json(cfd);
                std::string op = req.value("op", "");
                if (op == "terminate") {
                    running = false;
                    send_json(cfd, json{{"ok", true}});
                    ::close(cfd);
                    break;
                } else if (op == "end") {
                    json state = req.value("state", json::object());
                    end_game(state);
                    // no response needed
                } else if (op == "act") {
                    json state = req.value("state", json::object());
                    auto move = decide_action(state);
                    send_json(cfd, move);
                } else {
                    // back-compat: treat raw object as state
                    if (!req.contains("state") && !req.empty()) {
                        auto move = decide_action(req);
                        send_json(cfd, move);
                    } else {
                        send_json(cfd, json{{"error","unknown op"}});
                    }
                }
            } catch (const std::exception& e) {
                // ignore bad frames
            }
            ::close(cfd);
            // tiny sleep to be nice to CPU
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
        }

        ::close(fd);
        return 0;
    }
};

// --- CLI --------------------------------------------------------------------

static void print_help(const char* prog){
    std::cerr <<
    "Usage: " << prog << " [--host HOST] [--port PORT] [--name NAME]\n"
    "Defaults: --host 127.0.0.1  --port 5001  --name Simple\n";
}

int main(int argc, char** argv) {
    Bot bot;
    for (int i=1;i<argc;i++) {
        std::string a = argv[i];
        auto next = [&]()->const char*{
            if (i+1>=argc) { print_help(argv[0]); std::exit(2); }
            return argv[++i];
        };
        if (a=="--host") bot.host = next();
        else if (a=="--port") bot.port = std::stoi(next());
        else if (a=="--name") bot.name = next();
        else if (a=="-h" || a=="--help") { print_help(argv[0]); return 0; }
        else { std::cerr << "Unknown arg: " << a << "\n"; print_help(argv[0]); return 2; }
    }
    return bot.serve();
}

