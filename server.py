#!/usr/bin/env python3
import socket
import threading
import json
import sys
import os
import traceback
from typing import List

class TicTacToe3DServer:
    def __init__(self, host='0.0.0.0', port=None, max_players=2):
        # Render provides PORT environment variable
        if port is None:
            port = int(os.environ.get('PORT', 5555))

        self.host = host
        self.port = port
        self.max_players = max_players

        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            self.server.bind((host, port))
        except OSError as e:
            print(f"Failed to bind to port {port}: {e}", flush=True)
            print(f"Available ports from Render: {os.environ.get('PORT', 'Not set')}", flush=True)
            raise

        self.server.listen(4)
        print(f"Server listening on {host}:{port}", flush=True)

        # Game state
        # Board as 4x4x4 list (z,y,x). 0 empty, -1 player 0 (X), 1 player 1 (O)
        self.board = [[[0 for _ in range(4)] for _ in range(4)] for _ in range(4)]
        self.current_player = 0  # 0 or 1
        self.winner = None  # None or 0/1
        self.last_move = None  # dict with player,z,y,x

        # Clients: list of dicts {sock,addr,player_id,thread}
        self.clients = []
        self.lock = threading.Lock()
        self.running = True

    def run(self):
        """Main accept loop. This is what your script expected to exist."""
        try:
            accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
            accept_thread.start()

            # Keep main thread alive; this process is run as a background worker
            while self.running:
                # Keep a small sleep to avoid busy-loop
                try:
                    threading.Event().wait(1.0)
                except KeyboardInterrupt:
                    break
        finally:
            self.shutdown()

    def _accept_loop(self):
        print("Accept loop started", flush=True)
        while self.running:
            try:
                client_sock, client_addr = self.server.accept()
            except OSError:
                break
            print(f"New connection from {client_addr}", flush=True)
            with self.lock:
                if len(self.clients) >= self.max_players:
                    # refuse extra clients politely
                    try:
                        client_sock.sendall((json.dumps({"type": "error", "message": "Server full"}) + "\n").encode())
                    except Exception:
                        pass
                    client_sock.close()
                    print(f"Refused connection from {client_addr}: server full", flush=True)
                    continue

                player_id = self._next_player_id()
                client_info = {
                    "sock": client_sock,
                    "addr": client_addr,
                    "player_id": player_id,
                    "thread": None,
                    "alive": True,
                }
                t = threading.Thread(target=self._client_thread, args=(client_info,), daemon=True)
                client_info["thread"] = t
                self.clients.append(client_info)
                t.start()

    def _next_player_id(self):
        used = {c["player_id"] for c in self.clients if c.get("alive")}
        for pid in range(self.max_players):
            if pid not in used:
                return pid
        # fallback (shouldn't reach)
        return len(used)

    def _client_thread(self, client_info):
        sock = client_info["sock"]
        pid = client_info["player_id"]
        addr = client_info["addr"]
        print(f"Starting client thread for player {pid} from {addr}", flush=True)

        # Send init message with assigned player id
        try:
            sock.sendall((json.dumps({"type": "init", "player_id": pid}) + "\n").encode())
        except Exception:
            pass

        # Send initial state
        self._broadcast_state()

        buffer = ""
        try:
            while client_info["alive"]:
                data = sock.recv(4096)
                if not data:
                    break
                try:
                    buffer += data.decode()
                except UnicodeDecodeError:
                    # ignore undecodable fragments
                    continue

                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        message = json.loads(line)
                    except Exception as e:
                        print(f"Malformed JSON from {addr}: {e}", flush=True)
                        continue
                    self._handle_message(client_info, message)
        except Exception as e:
            print(f"Client thread exception for {addr}: {e}", flush=True)
            traceback.print_exc()
        finally:
            print(f"Client {addr} disconnected (player {pid})", flush=True)
            client_info["alive"] = False
            try:
                sock.close()
            except Exception:
                pass
            with self.lock:
                # Remove from clients list
                self.clients = [c for c in self.clients if c is not client_info]
            # If a player left mid-game, we can optionally reset the board
            # For now, we broadcast updated state to remaining clients
            self._broadcast_state()

    def _handle_message(self, client_info, message):
        mtype = message.get("type")
        if mtype == "move":
            # Validate move structure
            try:
                z = int(message.get("z"))
                y = int(message.get("y"))
                x = int(message.get("x"))
            except Exception:
                return
            player = client_info["player_id"]
            with self.lock:
                if self.winner is not None:
                    # Game already finished; ignore moves
                    return
                if player != self.current_player:
                    # Not this player's turn
                    print(f"Ignoring move from player {player}: not their turn", flush=True)
                    return
                if not (0 <= z < 4 and 0 <= y < 4 and 0 <= x < 4):
                    print(f"Ignoring out-of-bounds move from {player}: {(z,y,x)}", flush=True)
                    return
                if self.board[z][y][x] != 0:
                    print(f"Ignoring illegal move from {player}: cell occupied {(z,y,x)}", flush=True)
                    return

                # Apply move
                self.board[z][y][x] = -1 if player == 0 else 1
                self.last_move = {"player": player, "z": z, "y": y, "x": x}
                # Check for winner after move
                winner = self._check_winner()
                if winner is not None:
                    self.winner = winner
                else:
                    # toggle turn
                    self.current_player = 1 - self.current_player

                # Broadcast updated state
                self._broadcast_state()
        else:
            # Unknown message types are ignored for now
            pass

    def _broadcast_state(self):
        state = {
            "type": "state",
            "board": self.board,
            "current_player": self.current_player,
            "winner": self.winner,
            "last_move": self.last_move,
        }
        data = (json.dumps(state) + "\n").encode()
        dead = []
        with self.lock:
            for c in list(self.clients):
                try:
                    if c.get("alive") and c.get("sock"):
                        c["sock"].sendall(data)
                except Exception:
                    # mark for removal
                    c["alive"] = False
                    dead.append(c)
            if dead:
                self.clients = [c for c in self.clients if c.get("alive")]

    def _check_winner(self):
        """Check for a 4-in-a-row winner. Returns 0 or 1 if found, else None.
           This is a brute-force check over all lines (reasonable for 4x4x4)."""
        # Convert -1/1 to player indices 0/1 mapping for easy comparison
        def val_to_player(v):
            if v == -1:
                return 0
            if v == 1:
                return 1
            return None

        lines = []

        # rows (x) for each z,y
        for z in range(4):
            for y in range(4):
                lines.append([(z, y, x) for x in range(4)])
        # columns (y) for each z,x
        for z in range(4):
            for x in range(4):
                lines.append([(z, y, x) for y in range(4)])
        # vertical (z) for each y,x
        for y in range(4):
            for x in range(4):
                lines.append([(z, y, x) for z in range(4)])
        # face diagonals per layer (z fixed)
        for z in range(4):
            lines.append([(z, i, i) for i in range(4)])
            lines.append([(z, i, 3 - i) for i in range(4)])
        # vertical face diagonals x fixed
        for x in range(4):
            lines.append([(i, i, x) for i in range(4)])
            lines.append([(i, 3 - i, x) for i in range(4)])
        # vertical face diagonals y fixed
        for y in range(4):
            lines.append([(i, y, i) for i in range(4)])
            lines.append([(i, y, 3 - i) for i in range(4)])
        # 4 main space diagonals
        lines.append([(i, i, i) for i in range(4)])
        lines.append([(i, i, 3 - i) for i in range(4)])
        lines.append([(i, 3 - i, i) for i in range(4)])
        lines.append([(3 - i, i, i) for i in range(4)])

        for line in lines:
            vals = [self.board[z][y][x] for (z, y, x) in line]
            if all(v == -1 for v in vals):
                return 0
            if all(v == 1 for v in vals):
                return 1
        return None

    def shutdown(self):
        print("Shutting down server...", flush=True)
        self.running = False
        try:
            self.server.close()
        except Exception:
            pass
        with self.lock:
            for c in list(self.clients):
                try:
                    c["alive"] = False
                    if c.get("sock"):
                        c["sock"].close()
                except Exception:
                    pass
            self.clients = []

if __name__ == "__main__":
    # Render-specific: Get host/port from environment
    host = os.environ.get('HOST', '0.0.0.0')
    port_env = os.environ.get('PORT')

    if port_env:
        port = int(port_env)
    else:
        # For local development
        port = int(sys.argv[1]) if len(sys.argv) > 1 else 5555

    server = TicTacToe3DServer(host, port)
    server.run()