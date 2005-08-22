class LoginController < ApplicationController
  before_filter :defaults
  before_filter :authorize, :except => :login
  layout "hellanzb"
  
  def login
    if request.get?
      session[:user_id] = nil
    else
      if params[:password] == @password && params[:name] == @username
        session[:user_id] = 'logged_in'
        jumpto = session[:jumpto] || { :action => "index" }
        session[:jumpto] = nil
        redirect_to(:controller => 'hellanzb', :action => "index")
      else
        flash[:notice] = "Invalid user/password combination"
      end
    end
  end
  def logout
    session[:user_id] = nil
    flash[:notice] = "Logged out"
    redirect_to(:action => "login")
  end
end
